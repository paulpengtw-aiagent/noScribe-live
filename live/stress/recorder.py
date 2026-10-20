#!/usr/bin/env python3
"""Headless Chromium client that records one noScribe Live run in the browser.

Run it with the system Python that has Playwright, from the repo root:

    /usr/bin/python3 -I live/stress/recorder.py --out DIR [--url URL] [--max-seconds N]
        [--until-run-end] [--shots "5,30,60"] [--widths 1440,390] [--join-after S]
        [--offline-at S --offline-for D] [--extra-header "Name: value"] [--token TOKEN]

The first width is the metrics lane. Before the app loads, its page wraps window.EventSource and
records every open/error, hello, snapshot, runs and feed message with the browser receive time,
plus long tasks and per-second animation frame counts. Python polls window.__stress every 0.5 s.
Other widths only take screenshots.

Output in DIR: metrics.json (raw arrays and summary), arrivals.tsv (one row per segment) and PNG
screenshots named <t>s-<width>.png, run_end-<t>s-<width>.png and exit-<t>s-<width>.png. The one-line
JSON summary goes to stdout. Progress goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import statistics
import sys
import time
from pathlib import Path
from typing import Any

END_GRACE_S = 4.0            # keep recording this long after the run's end is seen
POLL_EVERY_S = 0.5           # how often Python reads window.__stress
TERMINAL_STATUSES = ("finished", "canceled", "error", "stale")

# Runs in every document of the metrics lane before the app's own scripts.
INIT_JS = r"""
(() => {
  if (window.__stressInstalled) return;
  window.__stressInstalled = true;
  const S = {
    opens: [], errors: [], hello: [], snapshots: [], feeds: [], runs: [],
    longtasks: [], longtaskSupported: false, longtaskError: null, frames: {},
    followed: null, followedStatus: null, endSeen: null, instances: 0,
  };
  window.__stress = S;
  const now = () => Date.now() / 1000;
  const TERMINAL = ["finished", "canceled", "error", "stale"];
  const Native = window.EventSource;
  if (Native) {
    const Wrapped = function EventSource(url, init) {
      const es = new Native(url, init);
      const inst = ++S.instances;
      es.addEventListener("open", () => S.opens.push({ t: now(), inst }));
      es.addEventListener("error", () => S.errors.push({ t: now(), inst, readyState: es.readyState }));
      es.addEventListener("hello", (e) => {
        const d = JSON.parse(e.data);
        S.hello.push({ t: now(), server_t: d.server_t, runs: (d.runs || []).length, inst });
      });
      es.addEventListener("snapshot", (e) => {
        const d = JSON.parse(e.data);
        const events = d.events || [];
        const status = d.summary ? d.summary.status : null;
        S.followed = d.run_id || null;
        if (status) S.followedStatus = status;
        S.snapshots.push({
          t: now(), run_id: d.run_id || null, segments: events.filter((ev) => ev.type === "segment").length,
          events: events.length, status, inst,
        });
      });
      es.addEventListener("runs", (e) => {
        const d = JSON.parse(e.data);
        const list = d.runs || [];
        const top = list[0] || null;
        const entry = list.find((r) => r.run_id === S.followed) || null;
        S.runs.push({ t: now(), n: list.length, top: top ? top.run_id : null,
                      followed: S.followed, followed_status: entry ? entry.status : null, inst });
        // The server sends `runs` before the `snapshot` of a switch, so only judge the followed run
        // when it is also the newest run (the one latest-mode follows).
        if (top && entry && top.run_id === S.followed) {
          S.followedStatus = entry.status;
          if (TERMINAL.includes(entry.status) && !S.endSeen) S.endSeen = { t: now(), reason: "runs:" + entry.status };
        }
      });
      es.addEventListener("feed", (e) => {
        const msg = JSON.parse(e.data);
        const ev = msg.event || {};
        const rec = { t: now(), run_id: msg.run_id, type: ev.type, seq: ev.seq, inst };
        if (ev.type === "segment") {
          rec.cli_t = ev.t; rec.index = ev.index; rec.speaker = ev.speaker; rec.text = ev.text;
        }
        S.feeds.push(rec);
        if (ev.type === "run_end" && msg.run_id === S.followed) {
          if (ev.status) S.followedStatus = ev.status;
          if (!S.endSeen) S.endSeen = { t: now(), reason: "run_end" };
        }
      });
      return es;
    };
    Wrapped.prototype = Native.prototype;
    Wrapped.CONNECTING = Native.CONNECTING;
    Wrapped.OPEN = Native.OPEN;
    Wrapped.CLOSED = Native.CLOSED;
    window.EventSource = Wrapped;
  }
  try {
    const po = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        S.longtasks.push({ t: (performance.timeOrigin + e.startTime) / 1000, dur: e.duration });
      }
    });
    po.observe({ type: "longtask", buffered: true });
    S.longtaskSupported = true;
  } catch (err) {
    S.longtaskError = String(err);
  }
  const tick = () => {
    const sec = Math.floor(Date.now() / 1000);
    S.frames[sec] = (S.frames[sec] || 0) + 1;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""

POLL_JS = """() => ({
  s: window.__stress || null,
  dom: document.querySelectorAll('[role="log"] .segment').length,
})"""

DOM_JS = """() => document.querySelectorAll('[role="log"] .segment').length"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Headless Chromium client that records a noScribe Live run.")
    p.add_argument("--url", default="http://127.0.0.1:8765/")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--max-seconds", type=float, default=1800.0, help="stop after N seconds (default 1800)")
    p.add_argument("--until-run-end", action="store_true",
                   help="stop 4 s after run_end for the followed run (or a terminal runs status)")
    p.add_argument("--shots", default="5,30,60", help='seconds after start to screenshot, e.g. "5,30,60"')
    p.add_argument("--widths", default="1440,390", help="viewport widths, one context each; first records metrics")
    p.add_argument("--join-after", type=float, default=0.0, help="open the page S seconds after start")
    p.add_argument("--offline-at", type=float, default=None, help="take the metrics context offline at S seconds")
    p.add_argument("--offline-for", type=float, default=10.0, help="seconds offline (default 10)")
    p.add_argument("--extra-header", action="append", default=[], help='extra HTTP header, "Name: value"')
    p.add_argument("--token", default=None, help="if set, first navigate to URL?token=TOKEN")
    args = p.parse_args(argv)
    if args.max_seconds <= 0:
        p.error("--max-seconds must be positive")
    if args.offline_at is not None and args.offline_for <= 0:
        p.error("--offline-for must be positive")
    return args


def _percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile, q in 0..100."""
    if not values:
        return None
    data = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(data)))
    return data[rank - 1]


def _r(x: float | None, digits: int = 1) -> float | None:
    return None if x is None else round(x, digits)


def _fmt_t(t: float) -> str:
    return f"{t:g}"


def _mobile_opts(width: int) -> dict[str, Any]:
    if width == 390:
        return {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
                "device_scale_factor": 2}
    return {"viewport": {"width": width, "height": 900}}


def fps_stats(frames: dict[int, int]) -> dict[str, float | None]:
    """Per-second frame counts, ignoring the first 2 s and the last (partial) second."""
    keys = sorted(frames)
    if len(keys) < 4:
        return {"median": None, "p5": None, "min": None}
    kept = [k for k in keys if k >= keys[0] + 2][:-1]
    values = [float(frames[k]) for k in kept]
    if not values:
        return {"median": None, "p5": None, "min": None}
    return {"median": _r(statistics.median(values)), "p5": _r(_percentile(values, 5)),
            "min": _r(min(values))}


def summarize(state: dict[str, Any], dom_count: int | None, console_errors: int) -> dict[str, Any]:
    feeds = state.get("feeds") or []
    segs = [f for f in feeds if f.get("type") == "segment" and f.get("cli_t") is not None]
    latencies = [(f["t"] - f["cli_t"]) * 1000.0 for f in segs]
    longtasks = state.get("longtasks") or []
    durs = [lt["dur"] for lt in longtasks]
    frames = {int(k): int(v) for k, v in (state.get("frames") or {}).items()}
    opens = state.get("opens") or []
    summary = {
        "segments_received": len({(f.get("run_id"), f.get("seq")) for f in segs}),
        "latency_ms": {"median": _r(statistics.median(latencies)) if latencies else None,
                       "p95": _r(_percentile(latencies, 95)) if latencies else None,
                       "max": _r(max(latencies)) if latencies else None},
        "reconnects": max(0, len(opens) - 1),
        "snapshots": len(state.get("snapshots") or []),
        "longtasks": {"count": len(durs), "total_ms": _r(sum(durs)) if durs else 0.0,
                      "max_ms": _r(max(durs)) if durs else 0.0},
        "fps": fps_stats(frames),
        "final_status": state.get("followedStatus"),
        "dom_segment_count": dom_count,
        "console_errors": console_errors,
        "run_id": state.get("followed"),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    if not widths:
        print("recorder: --widths is empty", file=sys.stderr)
        return 2
    shots = sorted(float(x) for x in args.shots.split(",") if x.strip())
    shots_requested = list(shots)  # `shots` is consumed by the loop; keep the request for metrics.json
    headers: dict[str, str] = {}
    for raw in args.extra_header:
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            print(f"recorder: --extra-header needs 'Name: value', got {raw!r}", file=sys.stderr)
            return 2
        headers[name.strip()] = value.strip()

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    stop_flag: dict[str, str | None] = {"reason": None}

    def on_signal(signum: int, _frame: Any) -> None:
        stop_flag["reason"] = f"signal{signum}"

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    console_log: list[dict[str, Any]] = []
    page_errors: list[dict[str, Any]] = []
    dom_log: list[dict[str, Any]] = []
    offline_log: list[dict[str, Any]] = []
    shot_log: list[str] = []
    lanes: list[dict[str, Any]] = []
    last_state: dict[str, Any] = {}
    last_dom: dict[int, int | None] = {}

    t0 = time.time()

    def elapsed() -> float:
        return time.time() - t0

    def take_shot(lane: dict[str, Any], name: str) -> None:
        try:
            lane["page"].screenshot(path=str(out / name))
            shot_log.append(name)
        except Exception as exc:  # keep recording even if one screenshot fails
            print(f"recorder: screenshot {name} failed: {exc}", file=sys.stderr)

    def poll(lane: dict[str, Any]) -> dict[str, Any] | None:
        try:
            if lane["metrics"]:
                return lane["page"].evaluate(POLL_JS)
            return {"s": None, "dom": lane["page"].evaluate(DOM_JS)}
        except Exception:  # mid-navigation or closed page
            return None

    def open_lane(lane: dict[str, Any]) -> None:
        if args.token:
            sep = "&" if "?" in args.url else "?"
            lane["page"].goto(f"{args.url}{sep}token={args.token}", wait_until="domcontentloaded", timeout=30000)
        lane["page"].goto(args.url, wait_until="domcontentloaded", timeout=30000)
        lane["joined"] = True
        print(f"recorder: opened width={lane['width']} at {elapsed():.1f}s", file=sys.stderr)

    reason = None
    joined = False
    offline_state: str | None = None
    end_at: float | None = None
    end_info: dict[str, Any] | None = None
    next_poll = 0.0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for index, width in enumerate(widths):
                opts = _mobile_opts(width)
                if headers:
                    opts["extra_http_headers"] = headers
                ctx = browser.new_context(**opts)
                if index == 0:
                    ctx.add_init_script(INIT_JS)
                page = ctx.new_page()
                page.on("console", lambda msg, w=width: console_log.append(
                    {"t": _r(elapsed(), 2), "width": w, "type": msg.type, "text": msg.text})
                    if msg.type == "error" else None)
                page.on("pageerror", lambda exc, w=width: page_errors.append(
                    {"t": _r(elapsed(), 2), "width": w, "text": str(exc)}))
                lanes.append({"width": width, "ctx": ctx, "page": page, "metrics": index == 0, "joined": False})

            metrics_lane = lanes[0]
            while reason is None:
                e = elapsed()
                if not joined and e >= args.join_after:
                    for lane in lanes:
                        open_lane(lane)
                    joined = True
                if args.offline_at is not None and offline_state is None and e >= args.offline_at:
                    metrics_lane["ctx"].set_offline(True)
                    offline_state = "on"
                    offline_log.append({"t": _r(e, 2), "offline": True})
                    print(f"recorder: offline at {e:.1f}s", file=sys.stderr)
                if (offline_state == "on" and args.offline_at is not None
                        and e >= args.offline_at + args.offline_for):
                    metrics_lane["ctx"].set_offline(False)
                    offline_state = "off"
                    offline_log.append({"t": _r(e, 2), "offline": False})
                    print(f"recorder: back online at {e:.1f}s", file=sys.stderr)
                while shots and shots[0] <= e:
                    t_shot = shots.pop(0)
                    for lane in lanes:
                        take_shot(lane, f"{_fmt_t(t_shot)}s-{lane['width']}.png")
                if joined and e >= next_poll:
                    next_poll = e + POLL_EVERY_S
                    for lane in lanes:
                        result = poll(lane)
                        if result is None:
                            continue
                        dom_now = result.get("dom")
                        last_dom[lane["width"]] = dom_now
                        dom_log.append({"t": _r(e, 2), "width": lane["width"], "dom": dom_now})
                        if lane["metrics"] and result.get("s"):
                            last_state = result["s"]
                            seen = last_state.get("endSeen")
                            if seen and end_at is None:
                                end_info = seen
                                end_at = float(seen["t"]) + END_GRACE_S
                                print(f"recorder: run end seen ({seen['reason']}) at {e:.1f}s", file=sys.stderr)
                                for other in lanes:
                                    take_shot(other, f"run_end-{_fmt_t(round(e, 1))}s-{other['width']}.png")
                if args.until_run_end and end_at is not None and time.time() >= end_at:
                    reason = "run_end"
                elif e >= args.max_seconds:
                    reason = "max_seconds"
                elif stop_flag["reason"]:
                    reason = stop_flag["reason"]
                else:
                    time.sleep(0.1)

            exit_t = round(elapsed(), 1)
            if offline_state == "on":
                metrics_lane["ctx"].set_offline(False)
                offline_log.append({"t": _r(elapsed(), 2), "offline": False, "note": "at exit"})
            final = poll(metrics_lane)
            if final and final.get("s"):
                last_state = final["s"]
            for lane in lanes:
                take_shot(lane, f"exit-{_fmt_t(exit_t)}s-{lane['width']}.png")
                result = poll(lane)
                if result is not None:
                    last_dom[lane["width"]] = result.get("dom")
        finally:
            browser.close()

    total_s = round(elapsed(), 2)
    console_errors = len(console_log) + len(page_errors)
    dom_final = last_dom.get(widths[0])
    summary = summarize(last_state, dom_final, console_errors)
    summary["dom_segment_count_by_width"] = {str(k): v for k, v in last_dom.items()}
    summary["stop_reason"] = reason
    summary["duration_s"] = total_s
    summary["screenshots"] = len(shot_log)

    metrics = {
        "config": {"url": args.url, "widths": widths, "shots": shots_requested, "until_run_end": args.until_run_end,
                   "join_after": args.join_after, "offline_at": args.offline_at,
                   "offline_for": args.offline_for, "token": bool(args.token),
                   "extra_headers": sorted(headers)},
        "started_at": t0,
        "end_seen": end_info,
        "stop_reason": reason,
        "offline": offline_log,
        "dom": dom_log,
        "console_errors": console_log,
        "page_errors": page_errors,
        "screenshots": shot_log,
        "state": last_state,
        "summary": summary,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    rows = ["seq\tindex\tcli_t\trecv_t\tlatency_ms\tspeaker\ttext40"]
    for f in last_state.get("feeds") or []:
        if f.get("type") != "segment" or f.get("cli_t") is None:
            continue
        text40 = str(f.get("text") or "")[:40].replace("\t", " ").replace("\n", " ")
        latency = (f["t"] - f["cli_t"]) * 1000.0
        rows.append(f"{f.get('seq')}\t{f.get('index')}\t{f['cli_t']:.3f}\t{f['t']:.3f}\t"
                    f"{latency:.1f}\t{f.get('speaker') or ''}\t{text40}")
    (out / "arrivals.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, separators=(", ", ": ")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
