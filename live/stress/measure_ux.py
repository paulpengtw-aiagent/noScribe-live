#!/usr/bin/env python3
"""UX measurements for noScribe Live: axe-core on a finished run, CLS during a replay, the initial
bundle, and screenshots. Prints one JSON summary (or a table with --matrix) and writes it to
OUTDIR/summary.json.

    /usr/bin/python3 -I live/stress/measure_ux.py --static DIR --out OUTDIR [--axe PATH] [--port 8775]
        [--python PY] [--work DIR] [--locale en|zh-TW] [--theme dark|light|both] [--easy] [--widths 1440,390]
    /usr/bin/python3 -I live/stress/measure_ux.py --matrix --static DIR --out OUTDIR [--axe PATH] [--port P]

  --locale  sets localStorage key noscribe-live-locale (src/i18n) before the app loads, so axe and the
           shots run in that UI language and the html lang is checked. Default: no key is set (the
           browser language decides, en-US in Playwright). Run once per locale with its own --out.
  --theme   dark, light or both (default both). The theme is set through the localStorage key read by
           src/hooks/use-theme.ts before load (axe configs only).
  --easy    easy view on: localStorage noscribe-live-easy = "1" before load (axe configs only). Off by
           default: the key is not set, and the app reads anything but "1" as off.
  --widths  comma list of 1440 and/or 390 (default 1440,390). 1440 is 1440x900, 390 is 390x844.
  --matrix  bundle and axe over palette(nordic,crimson) x theme(dark,light) x locale(en,zh-TW) x easy(off,on) x width(1440,390):
           32 configs on one finished run. Prints a compact table; summary.json holds every config.
           No CLS and no shots in this mode. --theme, --widths, --easy and --locale are rejected with it.

  axe      axe-core (violations only) on a FINISHED run, replayed at speed 8 first. One config per
           theme x width (default: dark and light at 1440x900 and 390x844), each with --easy and --locale
           as given. Per config: violation counts by impact (rules and nodes) and the color-contrast
           nodes, lowest ratio first (top 10 listed). Serious and critical are also listed by rule id.
  cls      Cumulative layout shift at 1440x900. The page is opened before a replay starts (speed 2,
           max-gap 2). CLS is the plain sum of layout-shift entries without hadRecentInput, read until
           run_end + 2 s. Also reports the largest shift and its source nodes.
  bundle   Bytes of the initial JS and CSS named by STATIC/index.html (entry script, modulepreload,
           stylesheet), read from disk. JS also gets gzip level 6 sizes per file and in total.
  shots    Dark screenshots of the finished run at 390x844 and 430x932, viewport and full page
           (default mode only).

The script starts its own server (`python -m server`, cwd live/) and its own replays, on --port only.
It signals only processes it started and aborts when the port is already in use. WORK (default
OUTDIR/work) holds the copied source feed, the feeds dirs and the logs. The source feed under
/workspace/noScribe-live/live/feeds is read only. Exit code 0 only if every measure ran.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent            # live/stress
LIVE_DIR = HERE.parent                            # cwd for `python -m server` and `python -m server.replay`
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_AXE = "/tmp/nslive-r5/axe.min.js"
FEEDS_SRC = Path("/workspace/noScribe-live/live/feeds")  # read only
DEMO_NAME = "20261020-052449-demo-en-zh.ndjson"          # 50 segments, 2 speakers, EN + ZH
THEME_KEY = "noscribe-live-theme"                        # src/hooks/use-theme.ts
EASY_KEY = "noscribe-live-easy"                          # src/hooks/use-easy-view.ts ("1" on; unset or "0" off)
LOCALE_KEY = "noscribe-live-locale"                      # src/i18n (values: en | zh-TW)
LOCALES = ("en", "zh-TW")
THEMES = ("dark", "light")
PALETTE_KEY = "noscribe-live-palette"                   # matrix dimension; no palette picker in live/web/src yet
PALETTES = ("nordic", "crimson")
DEFAULT_PORT = 8775
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
PHONE_LARGE = {"width": 430, "height": 932}
WIDTHS = {1440: DESKTOP, 390: PHONE}                     # --widths values -> viewport
SHOT_VIEWPORTS = (PHONE, PHONE_LARGE)
IMPACTS = ("critical", "serious", "moderate", "minor")

# Runs before the app's scripts in every document. Records the events the page receives (from `snapshot`
# and `feed`), so the script knows when a replay's run_end has reached the page.
INIT_JS = r"""
(() => {
  if (window.__nsObs) return;
  const O = { feeds: [] };
  window.__nsObs = O;
  const Native = window.EventSource;
  if (!Native) return;
  const note = (events, runId) => {
    for (const ev of events || []) {
      if (ev && ev.type) O.feeds.push({ run_id: runId, type: ev.type });
    }
  };
  const Wrapped = function EventSource(url, init) {
    const es = new Native(url, init);
    es.addEventListener("snapshot", (e) => {
      try { const d = JSON.parse(e.data); note(d.events, d.run_id); } catch (err) {}
    });
    es.addEventListener("feed", (e) => {
      try { const m = JSON.parse(e.data); note([m.event], m.run_id); } catch (err) {}
    });
    return es;
  };
  Wrapped.prototype = Native.prototype;
  Wrapped.CONNECTING = Native.CONNECTING;
  Wrapped.OPEN = Native.OPEN;
  Wrapped.CLOSED = Native.CLOSED;
  window.EventSource = Wrapped;
})();
"""

# Layout-shift observer, installed before any page script so buffered entries from page load are kept.
CLS_JS = r"""
(() => {
  if (window.__nsCLS) return;
  const S = { total: 0, shifts: [], excluded_recent_input: 0, observer: 'none' };
  window.__nsCLS = S;
  const describe = (el) => {
    if (!el || !el.tagName) return null;
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const tid = el.getAttribute && el.getAttribute('data-testid');
    if (tid) s += '[data-testid="' + tid + '"]';
    const cls = el.classList ? Array.from(el.classList).slice(0, 4) : [];
    if (cls.length) s += '.' + cls.join('.');
    return s;
  };
  try {
    const po = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.hadRecentInput) { S.excluded_recent_input += 1; continue; }
        S.total += e.value;
        if (e.value > 0) {
          S.shifts.push({ value: e.value, start: e.startTime,
                          sources: (e.sources || []).map((src) => describe(src.node)) });
        }
      }
    });
    po.observe({ type: 'layout-shift', buffered: true });
    S.observer = 'ok';
  } catch (err) {
    S.observer = 'error: ' + err;
  }
})();
"""

AXE_JS = "async () => (await axe.run(document, { resultTypes: ['violations'] })).violations"
SEG_COUNT_JS = "() => document.querySelectorAll('[data-segment-seq]').length"
THEME_READ_JS = "() => document.documentElement.dataset.theme || null"
EASY_READ_JS = "() => document.documentElement.getAttribute('data-easy')"
ENDED_JS = "() => (window.__nsObs ? window.__nsObs.feeds : [])"
CLS_READ_JS = "() => window.__nsCLS || null"


def theme_script(theme: str) -> str:
    return "(() => { try { localStorage.setItem('%s', '%s'); } catch (e) {} })();" % (THEME_KEY, theme)


def locale_script(locale: str) -> str:
    return "(() => { try { localStorage.setItem('%s', '%s'); } catch (e) {} })();" % (LOCALE_KEY, locale)


def easy_script() -> str:
    return "(() => { try { localStorage.setItem('%s', '1'); } catch (e) {} })();" % EASY_KEY


def palette_script(palette: str) -> str:
    return "(() => { try { localStorage.setItem('%s', '%s'); } catch (e) {} })();" % (PALETTE_KEY, palette)


LANG_JS = "() => document.documentElement.getAttribute('lang')"


def page_scripts(base: list[str], locale: str | None, easy: bool = False,
                 palette: str | None = None) -> list[str]:
    extra = ([locale_script(locale)] if locale else []) + ([easy_script()] if easy else [])
    extra += [palette_script(palette)] if palette else []
    return base + extra


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # unwinds through `finally`, so child processes are killed


# ---- small helpers ---------------------------------------------------------------------------------
def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def poll(fn: Callable[[], Any], timeout: float, step: float = 0.3) -> bool:
    """Call fn until it is truthy or the timeout passes. An exception (page navigating) counts as not yet."""
    end = time.monotonic() + timeout
    while True:
        try:
            if fn():
                return True
        except Exception:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(step)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def estimate_replay(events: list[dict[str, Any]], speed: float, max_gap: float) -> float:
    """Wall time server.replay takes: each pause is min(gap / speed, max_gap)."""
    total = 0.0
    prev: float | None = None
    for ev in events:
        t = ev.get("t")
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            continue
        if prev is not None:
            total += min(max(0.0, t - prev) / speed, max_gap)
        prev = t
    return round(total, 1)


def run_id_of(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("run_id"):
                    return str(ev["run_id"])
    except OSError:
        pass
    return None


def open_page(browser: Any, viewport: dict[str, int], scripts: list[str], errs: list[str]) -> tuple[Any, Any]:
    ctx = browser.new_context(viewport=viewport)
    for script in scripts:
        ctx.add_init_script(script)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: errs.append(str(exc)[:200]))
    return ctx, page


def ended_on_page(page: Any, run_id: str) -> bool:
    feeds = page.evaluate(ENDED_JS) or []
    return any(e.get("run_id") == run_id and e.get("type") == "run_end" for e in feeds)


def wait_finished(page: Any, run_id: str, expected: int) -> dict[str, Any]:
    """Wait for the whole finished run on the page (run_end seen, all segments rendered), then settle."""
    ended = poll(lambda: ended_on_page(page, run_id), 40)
    poll(lambda: int(page.evaluate(SEG_COUNT_JS)) >= expected, 30)
    page.wait_for_timeout(1500)
    return {"run_end_seen": ended, "segments_rendered": int(page.evaluate(SEG_COUNT_JS))}


def target_text(target: Any) -> str:
    """axe target: a list with one selector per frame or shadow level."""
    if isinstance(target, str):
        return target
    parts = []
    for item in target or []:
        parts.append(" >>> ".join(map(str, item)) if isinstance(item, list) else str(item))
    return " ".join(parts)


def contrast_data(node: dict[str, Any]) -> dict[str, Any]:
    """The color-contrast check data (fgColor, bgColor, contrastRatio) of a node."""
    for key in ("any", "all", "none"):
        for check in node.get(key) or []:
            data = check.get("data")
            if isinstance(data, dict) and ("contrastRatio" in data or "fgColor" in data):
                return data
    return {}


def summarize_axe(violations: list[dict[str, Any]]) -> dict[str, Any]:
    rules_by_impact = {k: 0 for k in IMPACTS}
    nodes_by_impact = {k: 0 for k in IMPACTS}
    rules: list[dict[str, Any]] = []
    contrast: list[dict[str, Any]] = []
    for v in violations:
        impact = v.get("impact") or "unknown"
        nodes = v.get("nodes") or []
        rules_by_impact[impact] = rules_by_impact.get(impact, 0) + 1
        nodes_by_impact[impact] = nodes_by_impact.get(impact, 0) + len(nodes)
        rules.append({"id": v.get("id"), "impact": impact, "nodes": len(nodes)})
        if v.get("id") == "color-contrast":
            for node in nodes:
                data = contrast_data(node)
                contrast.append({
                    "target": target_text(node.get("target")),
                    "fg": data.get("fgColor"),
                    "bg": data.get("bgColor"),
                    "ratio": data.get("contrastRatio"),
                })
    contrast.sort(key=lambda c: (c["ratio"] is None, c["ratio"] if isinstance(c["ratio"], (int, float)) else 0))
    return {
        "violation_rules": len(violations),
        "violation_nodes": sum(len(v.get("nodes") or []) for v in violations),
        "rules_by_impact": rules_by_impact,
        "nodes_by_impact": nodes_by_impact,
        "rules": rules,
        "color_contrast_nodes": len(contrast),
        "color_contrast_top10": contrast[:10],  # lowest contrast ratio first
    }


class _IndexRefs(HTMLParser):
    """Initial-load assets of index.html: script src, modulepreload and stylesheet links."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "script" and a.get("src"):
            self.refs.append(("entry" if a.get("type", "").lower() == "module" else "script", a["src"]))
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower().split()
            if "modulepreload" in rel:
                self.refs.append(("modulepreload", a["href"]))
            elif "stylesheet" in rel:
                self.refs.append(("stylesheet", a["href"]))


def measure_bundle(static: Path) -> dict[str, Any]:
    refs = _IndexRefs()
    refs.feed((static / "index.html").read_text(encoding="utf-8"))
    files: list[dict[str, Any]] = []
    for role, href in refs.refs:
        rel = href.split("#")[0].split("?")[0].lstrip("/")
        path = static / rel
        exists = path.is_file()
        is_css = role == "stylesheet" or path.suffix.lower() == ".css"
        data = path.read_bytes() if exists else None
        files.append({
            "role": role,
            "file": rel,
            "kind": "css" if is_css else "js",
            "bytes": len(data) if data is not None else None,
            "gzip6_bytes": len(gzip.compress(data, compresslevel=6, mtime=0)) if data is not None else None,
        })

    def total(kind: str, key: str) -> int:
        return sum(f[key] or 0 for f in files if f["kind"] == kind)

    js, css = total("js", "bytes"), total("css", "bytes")
    js_gz, css_gz = total("js", "gzip6_bytes"), total("css", "gzip6_bytes")
    return {
        "index": str(static / "index.html"),
        "files": files,
        "initial_js_bytes": js,
        "initial_js_gzip6_bytes": js_gz,
        "initial_css_bytes": css,
        "initial_css_gzip6_bytes": css_gz,
        "initial_total_bytes": js + css,
        "initial_total_gzip6_bytes": js_gz + css_gz,
        "missing": [f["file"] for f in files if f["bytes"] is None],
    }


def default_combos(themes: tuple[str, ...], widths: list[int], locale: str | None, easy: bool) -> list[dict[str, Any]]:
    """One axe config per theme x width, with the given locale and easy flag."""
    combos: list[dict[str, Any]] = []
    for theme in themes:
        for width in widths:
            vp = WIDTHS[width]
            label = f"{theme}_{vp['width']}x{vp['height']}" + ("_easy" if easy else "")
            combos.append({"label": label, "theme": theme, "locale": locale, "easy": easy, "viewport": vp})
    return combos


def matrix_combos() -> list[dict[str, Any]]:
    """palette x theme x locale x easy x width: 32 axe configs."""
    combos: list[dict[str, Any]] = []
    for palette in PALETTES:
        for theme in THEMES:
            for locale in LOCALES:
                for easy in (False, True):
                    for width, vp in WIDTHS.items():
                        label = f"{palette}-{theme}-{locale}-{'easy' if easy else 'off'}-{width}"
                        combos.append({"label": label, "palette": palette, "theme": theme, "locale": locale,
                                       "easy": easy, "viewport": vp})
    return combos


# ---- own server and replays ------------------------------------------------------------------------
class Rig:
    """Starts and stops this script's own server and replays on one port. Only pids it spawned are signalled."""

    def __init__(self, python: str, port: int, static: Path, work: Path) -> None:
        self.python = python
        self.port = port
        self.static = static
        self.logs = work / "logs"
        self.feeds_root = work / "feeds"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.feeds_root.mkdir(parents=True, exist_ok=True)
        self.procs: list[subprocess.Popen] = []

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def feeds_dir(self, tag: str) -> Path:
        directory = self.feeds_root / tag
        shutil.rmtree(directory, ignore_errors=True)  # only our own scratch dir
        directory.mkdir(parents=True)
        return directory

    def _spawn(self, cmd: list[str], log_name: str) -> subprocess.Popen:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep .pyc files out of the worktree
        with open(self.logs / log_name, "ab") as log:
            proc = subprocess.Popen(cmd, cwd=LIVE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=True)
        self.procs.append(proc)
        return proc

    def _healthy(self) -> bool:
        with urllib.request.urlopen(self.base + "api/health", timeout=2) as resp:
            return resp.status == 200

    def start_server(self, feeds: Path, tag: str) -> subprocess.Popen:
        if not poll(lambda: not port_busy(self.port), 10):
            raise RuntimeError(f"port {self.port} still in use before starting the {tag} server")
        cmd = [self.python, "-m", "server", "--port", str(self.port), "--feeds", str(feeds),
               "--static", str(self.static)]
        proc = self._spawn(cmd, f"server-{tag}.log")
        if not poll(self._healthy, 20):
            self.stop(proc)
            raise RuntimeError(f"server on port {self.port} did not answer /api/health "
                               f"(log {self.logs / f'server-{tag}.log'})")
        return proc

    def start_replay(self, src: Path, feeds: Path, speed: float, max_gap: float, tag: str) -> subprocess.Popen:
        cmd = [self.python, "-m", "server.replay", str(src), "--feeds", str(feeds),
               "--speed", str(speed), "--max-gap", str(max_gap)]
        return self._spawn(cmd, f"replay-{tag}.log")

    def replay_run(self, feeds: Path, timeout: float = 15.0) -> tuple[Path, str]:
        """The newest replay feed file in feeds and its run id, once the replay has written it."""
        found: dict[str, Any] = {}

        def ready() -> bool:
            for path in sorted(feeds.glob("replay-*.ndjson")):
                run_id = run_id_of(path)
                if run_id:
                    found["v"] = (path, run_id)
                    return True
            return False

        if not poll(ready, timeout):
            raise RuntimeError(f"no replay feed appeared in {feeds}")
        return found["v"]

    @staticmethod
    def stop(proc: subprocess.Popen | None, grace: float = 5.0) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # pgid == pid (start_new_session)
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait(timeout=10)

    def reap(self) -> None:
        for proc in self.procs:
            self.stop(proc, grace=2.0)


# ---- measures --------------------------------------------------------------------------------------
def axe_config(browser: Any, rig: Rig, run_id: str, expected: int, axe_path: Path, combo: dict[str, Any]) -> dict[str, Any]:
    errs: list[str] = []
    vp = combo["viewport"]
    scripts = page_scripts([INIT_JS, theme_script(combo["theme"])], combo["locale"], combo["easy"],
                           combo.get("palette"))
    ctx, page = open_page(browser, vp, scripts, errs)
    try:
        page.goto(rig.base, wait_until="domcontentloaded", timeout=30000)
        state = wait_finished(page, run_id, expected)
        page.add_script_tag(path=str(axe_path))
        violations = page.evaluate(AXE_JS) or []
        return {
            "viewport": f"{vp['width']}x{vp['height']}",
            "palette": combo.get("palette") or "default",
            "theme": combo["theme"],
            "theme_applied": page.evaluate(THEME_READ_JS),
            "locale": combo["locale"] or "default",
            "html_lang": page.evaluate(LANG_JS),
            "easy": combo["easy"],
            "easy_applied": page.evaluate(EASY_READ_JS) == "true",
            **state,
            **summarize_axe(violations),
            "page_errors": errs[:3],
        }
    finally:
        ctx.close()


def measure_finished(rig: Rig, browser: Any, src: Path, axe_path: Path, out: Path,
                     summary: dict[str, Any], combos: list[dict[str, Any]], locale: str | None,
                     with_shots: bool) -> None:
    """axe-core on the finished run for each config; with with_shots, dark screenshots at two phone sizes."""
    print(f"== finished run: axe-core on {len(combos)} config(s)" + (" and screenshots" if with_shots else ""),
          flush=True)
    feeds = rig.feeds_dir("finished")
    expected = summary["source_segments"]
    server = rig.start_server(feeds, "finished")
    try:
        summary["axe_run"] = {"replay": {"speed": 8, "max_gap": 2},
                              "estimated_replay_s": estimate_replay(load_events(src), 8, 2)}
        replay = rig.start_replay(src, feeds, speed=8, max_gap=2, tag="finished")
        replay.wait(timeout=900)
        _path, run_id = rig.replay_run(feeds)
        summary["axe_run"]["run_id"] = run_id

        axe: dict[str, Any] = {}
        for combo in combos:
            label = combo["label"]
            try:
                axe[label] = axe_config(browser, rig, run_id, expected, axe_path, combo)
            except Exception as exc:
                axe[label] = {"error": f"{type(exc).__name__}: {str(exc).strip()[:300]}"}
                print(f"FAIL axe {label}: {axe[label]['error']}", flush=True)
        summary["axe"] = axe

        shots: list[str] = []
        for viewport in (SHOT_VIEWPORTS if with_shots else ()):
            ctx, page = open_page(browser, viewport, page_scripts([INIT_JS, theme_script("dark")], locale), [])
            try:
                page.goto(rig.base, wait_until="domcontentloaded", timeout=30000)
                wait_finished(page, run_id, expected)
                w, h = viewport["width"], viewport["height"]
                for kind, full in (("viewport", False), ("full", True)):
                    png = out / f"shot-{w}x{h}-{kind}.png"
                    page.screenshot(path=str(png), full_page=full)
                    shots.append(str(png))
            finally:
                ctx.close()
        summary["screenshots"] = shots
    finally:
        rig.stop(server)


def measure_cls(rig: Rig, browser: Any, src: Path, summary: dict[str, Any], locale: str | None = None) -> None:
    """CLS at 1440x900 with the page open before a replay (speed 2, max-gap 2) starts."""
    print("== CLS during a replay (1440x900)", flush=True)
    feeds = rig.feeds_dir("cls")
    expected_s = estimate_replay(load_events(src), 2, 2)
    server = rig.start_server(feeds, "cls")
    replay = None
    try:
        errs: list[str] = []
        ctx, page = open_page(browser, DESKTOP, page_scripts([INIT_JS, CLS_JS], locale), errs)
        try:
            page.goto(rig.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)  # the page is open and settled before the replay starts
            replay = rig.start_replay(src, feeds, speed=2, max_gap=2, tag="cls")
            _path, run_id = rig.replay_run(feeds)
            ended = poll(lambda: ended_on_page(page, run_id), expected_s + 120)
            page.wait_for_timeout(2000)  # run_end + 2 s
            data = page.evaluate(CLS_READ_JS) or {}
        finally:
            ctx.close()
        shifts = data.get("shifts") or []
        largest = max(shifts, key=lambda s: s.get("value", 0), default=None)
        summary["cls"] = {
            "viewport": "1440x900",
            "theme": "default",
            "locale": locale or "default",
            "replay": {"speed": 2, "max_gap": 2, "estimated_s": expected_s, "run_id": run_id},
            "run_end_seen": ended,
            "observer": data.get("observer"),
            "total_cls": round(float(data.get("total", 0.0)), 5),
            "shift_count": len(shifts),
            "excluded_recent_input": data.get("excluded_recent_input", 0),
            "largest_shift": None if largest is None else {
                "value": round(float(largest["value"]), 5),
                "start_time_ms": round(float(largest["start"]), 1),
                "sources": largest.get("sources") or [],
            },
            "page_errors": errs[:3],
        }
    finally:
        rig.stop(replay)
        rig.stop(server)


def record(errors: list[dict[str, str]], name: str, exc: BaseException) -> None:
    first = (str(exc).strip().splitlines() or [""])[0][:300]
    text = f"{type(exc).__name__}: {first}"
    errors.append({"phase": name, "error": text})
    print(f"FAIL {name}: {text}", flush=True)


def matrix_lines(axe: dict[str, Any]) -> list[str]:
    """Compact table: serious and critical as rules/nodes, then the rule ids of both (impact, nodes)."""
    head = f"{'palette':<8} {'theme':<6} {'locale':<6} {'easy':<4} {'width':<5} {'serious':>9} {'critical':>9}  rule ids (impact, nodes)"
    lines = [head, "-" * len(head)]
    for label, entry in axe.items():
        if "error" in entry:
            lines.append(f"ERROR {label}: {entry['error']}")
            continue
        ri, ni = entry["rules_by_impact"], entry["nodes_by_impact"]
        ser = f"{ri.get('serious', 0)}/{ni.get('serious', 0)}"
        crit = f"{ri.get('critical', 0)}/{ni.get('critical', 0)}"
        bad = sorted((r for r in entry["rules"] if r["impact"] in ("critical", "serious")),
                     key=lambda r: (r["impact"] != "critical", str(r["id"])))
        ids = ", ".join(f"{r['id']}({r['impact'][0]},{r['nodes']})" for r in bad) or "-"
        lines.append(f"{entry.get('palette', 'default'):<8} {entry['theme']:<6} {entry['locale']:<6} "
                     f"{'on' if entry['easy'] else 'off':<4} "
                     f"{entry['viewport'].split('x')[0]:<5} {ser:>9} {crit:>9}  {ids}")
    return lines


def print_matrix(summary: dict[str, Any], out: Path) -> None:
    bundle = summary.get("bundle") or {}
    for f in bundle.get("files", []):
        if f["kind"] == "js":
            print(f"bundle {f['role']:<13} {f['file']}: raw {f['bytes']} B, gzip-6 {f['gzip6_bytes']} B")
    print(f"bundle initial JS total: raw {bundle.get('initial_js_bytes')} B, "
          f"gzip-6 {bundle.get('initial_js_gzip6_bytes')} B; "
          f"CSS raw {bundle.get('initial_css_bytes')} B, gzip-6 {bundle.get('initial_css_gzip6_bytes')} B")
    print()
    print("\n".join(matrix_lines(summary.get("axe") or {})))
    print()
    print(f"summary: {out / 'summary.json'}  errors: {len(summary.get('errors') or [])}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UX measurements for noScribe Live: axe, CLS, bundle, shots.")
    parser.add_argument("--static", required=True, help="built frontend dir (has index.html), e.g. a dist dir")
    parser.add_argument("--out", required=True, help="output dir for summary.json and screenshots")
    parser.add_argument("--axe", default=DEFAULT_AXE, help="axe-core script to inject (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port for this script's own server (default: %(default)s)")
    parser.add_argument("--python", default=DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=None, help="scratch dir for feeds, logs and the source copy "
                                                     "(default: OUTDIR/work)")
    parser.add_argument("--locale", choices=LOCALES, default=None,
                        help="UI locale set in localStorage before load (default: none, browser language decides)")
    parser.add_argument("--theme", choices=(*THEMES, "both"), default=None,
                        help="axe themes (default: both)")
    parser.add_argument("--easy", action="store_true",
                        help="easy view on for the axe configs (localStorage noscribe-live-easy = 1)")
    parser.add_argument("--widths", default=None,
                        help="comma list of 1440 and/or 390 for the axe configs (default: 1440,390)")
    parser.add_argument("--matrix", action="store_true",
                        help="bundle and axe over palette x theme x locale x easy x width (32 configs); no CLS or shots")
    args = parser.parse_args(argv)
    if args.matrix:
        given = [flag for flag, val in (("--theme", args.theme), ("--widths", args.widths),
                                        ("--easy", args.easy), ("--locale", args.locale)) if val]
        if given:
            parser.error("--matrix enumerates theme, locale, easy and width; drop " + ", ".join(given))
    try:
        args.width_list = [int(w) for w in (args.widths or "1440,390").split(",") if w.strip()]
    except ValueError:
        parser.error(f"--widths takes a comma list of 1440 and 390, got {args.widths!r}")
    if not args.width_list or any(w not in WIDTHS for w in args.width_list):
        parser.error(f"--widths takes a comma list of 1440 and 390, got {args.widths!r}")
    args.theme_list = THEMES if args.theme in (None, "both") else (args.theme,)
    return args


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _exit_on_term)
    args = parse_args(argv)
    static = Path(args.static).resolve()
    out = Path(args.out).resolve()
    axe_path = Path(args.axe).resolve()
    work = Path(args.work).resolve() if args.work else out / "work"
    for label, path in (("index.html", static / "index.html"), ("axe script", axe_path),
                        ("source feed", FEEDS_SRC / DEMO_NAME)):
        if not path.is_file():
            print(f"FAIL setup: {label} missing: {path}", flush=True)
            return 2
    if port_busy(args.port):
        print(f"FAIL setup: port {args.port} already in use; not touching that process", flush=True)
        return 2
    try:
        from playwright.sync_api import sync_playwright  # imported here so a missing package is one clear line
    except ImportError as exc:
        print(f"FAIL setup: playwright is not importable with this python: {exc}", flush=True)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    src = work / "src" / DEMO_NAME
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FEEDS_SRC / DEMO_NAME, src)
    expected = sum(1 for ev in load_events(src) if ev.get("type") == "segment")

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "matrix" if args.matrix else "default",
        "static": str(static),
        "port": args.port,
        "work": str(work),
        "source": str(FEEDS_SRC / DEMO_NAME),
        "source_segments": expected,
        "locale": "matrix" if args.matrix else (args.locale or "default"),
        "theme": "matrix" if args.matrix else (args.theme or "both"),
        "widths": None if args.matrix else args.width_list,
        "easy": None if args.matrix else args.easy,
        "palette": "matrix" if args.matrix else None,
        "axe_expected": [c["label"] for c in matrix_combos()] if args.matrix else None,
    }
    errors: list[dict[str, str]] = []
    rig = Rig(args.python, args.port, static, work)
    try:
        print("== bundle", flush=True)
        try:
            summary["bundle"] = measure_bundle(static)
        except Exception as exc:
            record(errors, "bundle", exc)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                try:
                    if args.matrix:
                        measure_finished(rig, browser, src, axe_path, out, summary, matrix_combos(), None, False)
                    else:
                        combos = default_combos(args.theme_list, args.width_list, args.locale, args.easy)
                        measure_finished(rig, browser, src, axe_path, out, summary, combos, args.locale, True)
                except Exception as exc:
                    record(errors, "finished", exc)
                if not args.matrix:
                    try:
                        measure_cls(rig, browser, src, summary, args.locale)
                    except Exception as exc:
                        record(errors, "cls", exc)
            finally:
                browser.close()
    finally:
        rig.reap()

    summary["errors"] = errors
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    out.joinpath("summary.json").write_text(text + "\n", encoding="utf-8")
    if args.matrix:
        print_matrix(summary, out)
    else:
        print(text, flush=True)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
