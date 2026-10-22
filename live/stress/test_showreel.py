#!/usr/bin/env python3
"""Showreel checks for noScribe Live: continuous-flow reveal, cinematic pre-roll, speed control, Easy view,
reduced motion, and the pre-roll at phone widths.

Groups (--only, default all):
  flow     desktop 1440x900, page open before a real-speed replay (speed 1, max-gap 30). A page-side sampler
           counts the revealed graphemes every 50 ms, and every rAF frame records the count too. Idle = frames on
           which no grapheme was added since the previous frame, between the first segment and run_end (share of
           frames, and the longest idle run in ms); largest gap between visible additions; lag from run_end to an
           empty queue; rAF FPS; long tasks in the live window.
  preroll  page open before a real-speed replay: desktop 1440 and phone 390, en and zh-TW, dark. The pre-roll
           shows after run_start with terminal rows (audio, model, device, language, speakers). At the moment
           window.__nslivePreroll.active flips false the four stats must all be known. Afterwards the full UI
           (stage card and transcript) is visible. Screenshots go to WORK/shots. History: a finished run opened
           bare and with ?run=<id> never shows the pre-roll.
  speed    speed-control popover on a live run (speed 4): reading mode persists across reload; the keyboard on the
           slider sets a custom rate that persists. Easy view and reduced motion: no speed-control, and every
           segment shows its full text at first sight.
  phone    pre-roll at 360, 390 and 430 px wide, en and zh-TW (speed 2): no horizontal overflow.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_showreel.py [--only flow,preroll,speed,phone] [--port 8930]
        [--static DIR] [--python PY] [--work DIR]

Ports: flow --port, preroll +1, speed +2, phone +3. Each group starts its own `python -m server` and its own
replay through the Harness in test_ux.py. WORK (default /tmp/nslive-sr) holds src/ (a copy of the demo feed; the
original is read only), feeds/, logs/ and shots/. A group waits while the cgroup memory.current is above 18 GiB.
Exit code 0 only if every check passed. INFO lines carry measured numbers that have no threshold.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  shared harness: servers, replays, DOM helpers, check reporting

FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only
DEFAULT_WORK = Path("/tmp/nslive-sr")
GROUPS = ("flow", "preroll", "speed", "phone")
GROUP_PORT = {"flow": 0, "preroll": 1, "speed": 2, "phone": 3}
MEM_FILE = Path("/sys/fs/cgroup/memory.current")
MEM_LIMIT = 19327352832  # 18 GiB
MODEL = "breeze-asr-25"
AUDIO = "demo-en-zh"
RUN_END_RE = re.compile(r'"type":\s*"run_end"')
NEED_STATS = {"model", "device", "language", "speakers"}

# Page-side sampler (installed before the app): every 50 ms the revealed grapheme count, the segment count and the
# queue as the reveal reports it. Also rAF frame times and long tasks (Date.now() clock, same as the Python side).
FLOW_JS = r"""
(() => {
  if (window.__nsFlow) return;
  const F = { samples: [], frames: [], fr: [], longtasks: [] };
  window.__nsFlow = F;
  const text = (el) => { let t = '';
    const walk = (n) => { for (const c of n.childNodes) {
      if (c.nodeType === 3) t += c.nodeValue;
      else if (c.nodeType === 1 && !c.hasAttribute('data-unrevealed')) walk(c); } };
    walk(el); return t; };
  setInterval(() => {
    let n = 0, segs = 0;
    for (const el of document.querySelectorAll('[data-segment-seq]')) { segs += 1; n += text(el).trim().length; }
    const r = window.__nsliveReveal;
    F.samples.push({ t: Date.now(), n, segs, q: r ? r.queued : -1, bk: r ? r.backlogChars : -1 });
  }, 50);
  // Per frame: [Date.now(), graphemes shown]. Python marks a frame idle when its count did not grow since the previous one.
  const count = () => { let n = 0; for (const el of document.querySelectorAll('[data-segment-seq]')) n += text(el).trim().length; return n; };
  const frame = () => { if (F.frames.length < 60000) { const t = Date.now(); F.frames.push(t); F.fr.push([t, count()]); }
    requestAnimationFrame(frame); };
  requestAnimationFrame(frame);
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) F.longtasks.push([Date.now(), e.duration]); })
    .observe({ type: 'longtask', buffered: true }); } catch (e) {}
})();
"""

# Records, for every segment element, the text it shows the first time it is in the DOM (Easy view and reduced
# motion must show the full text at once).
SEEN_JS = r"""
(() => {
  if (window.__nsSeen) return;
  const seen = {};
  window.__nsSeen = seen;
  const text = (el) => { let t = '';
    const walk = (n) => { for (const c of n.childNodes) {
      if (c.nodeType === 3) t += c.nodeValue;
      else if (c.nodeType === 1 && !c.hasAttribute('data-unrevealed')) walk(c); } };
    walk(el); return t; };
  const scan = () => { for (const el of document.querySelectorAll('[data-segment-seq]')) {
    const k = el.getAttribute('data-segment-seq');
    if (!(k in seen)) seen[k] = { t: Date.now(), text: text(el) };
  } };
  // Init scripts run before <html> exists, so observe the document node itself (always present).
  new MutationObserver(scan).observe(document, { childList: true, subtree: true, characterData: true });
  scan();
})();
"""

SNAP_JS = """() => {
  const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
  const p = window.__nslivePreroll || null;
  return {
    t: Date.now(),
    preroll: vis(document.querySelector('[data-testid="preroll"]')),
    prerollCount: document.querySelectorAll('[data-testid="preroll"]').length,
    terminal: vis(document.querySelector('[data-testid="preroll-terminal"]')),
    active: p ? p.active : null,
    reason: p ? p.reason : null,
    lines: Array.from(document.querySelectorAll('[data-testid="preroll-line"]')).map((e) => ({
      id: e.getAttribute('data-line'), text: e.textContent.trim() })),
    stage: vis(document.querySelector('[data-testid="stage-card"]')),
    transcript: vis(document.querySelector('[data-testid="transcript-scroll"]')),
  };
}"""

OVERFLOW_JS = """() => { const de = document.documentElement, b = document.body;
  const pv = document.querySelector('[data-testid="preroll"]');
  const r = pv ? pv.getBoundingClientRect() : null;
  return { pre: !!r && r.height > 0, sw: de.scrollWidth, cw: de.clientWidth, bsw: b.scrollWidth, bcw: b.clientWidth }; }"""

EMPTY_JS = """() => { const r = window.__nsliveReveal; return !!r && r.queued === 0 && r.backlogChars === 0; }"""

SPEED_STATE_JS = "() => localStorage.getItem('noscribe-live-reveal')"

PREROLL_SPECS = (("1440-dark-en", 1440, 900, "en"), ("1440-dark-zh-TW", 1440, 900, "zh-TW"),
                 ("390-dark-en", 390, 844, "en"), ("390-dark-zh-TW", 390, 844, "zh-TW"))


def poll(fn: Any, timeout: float, step: float = 0.2) -> Any:
    end = time.time() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.time() >= end:
            return None
        time.sleep(step)


def info(name: str, detail: str) -> None:
    print(f"INFO {name}: {detail}", flush=True)


def wait_mem(tag: str) -> None:
    """Wait while the shared cgroup is above 18 GiB (bounded, so a stuck gauge cannot hang the run)."""
    for _ in range(120):
        try:
            cur = int(MEM_FILE.read_text().strip())
        except (OSError, ValueError):
            return
        if cur <= MEM_LIMIT:
            print(f"memory {cur / 2**30:.2f} GiB (<= 18 GiB) before {tag}", flush=True)
            return
        print(f"memory {cur / 2**30:.2f} GiB > 18 GiB; waiting before {tag}", flush=True)
        time.sleep(5)
    print(f"memory still above 18 GiB before {tag}; running anyway", flush=True)


def preset(theme: str, locale: str, easy: str | None = None) -> str:
    parts = [f"localStorage.setItem('noscribe-live-theme', {json.dumps(theme)});",
             f"localStorage.setItem('noscribe-live-locale', {json.dumps(locale)});"]
    if easy is not None:
        parts.append(f"localStorage.setItem('noscribe-live-easy', {json.dumps(easy)});")
    return "try { " + " ".join(parts) + " } catch (e) {}"


def new_ctx(browser: Any, w: int = 1440, hgt: int = 900, presets: str | None = None,
            reduced: bool = False, extras: tuple[str, ...] = ()) -> tuple[Any, Any]:
    kwargs: dict[str, Any] = {"viewport": {"width": w, "height": hgt}}
    if reduced:
        kwargs["reduced_motion"] = "reduce"
    ctx = browser.new_context(**kwargs)
    ctx.add_init_script(ux.INIT_JS)
    for js in extras:
        ctx.add_init_script(js)
    if presets:
        ctx.add_init_script(presets)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    return ctx, page


def run_end_at(path: Path, timeout: float) -> float | None:
    """Wall-clock ms at which the feed file holds run_end (the replay writes it at its own pace)."""
    def has() -> bool:
        try:
            return bool(RUN_END_RE.search(path.read_text(encoding="utf-8")))
        except OSError:
            return False
    if poll(has, timeout, 0.1):
        return time.time() * 1000.0
    return None


def feed_seg_texts(path: Path) -> dict[str, str]:
    """seq -> segment text as the feed sends it, whitespace-normalised."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "segment":
            out[str(ev["seq"])] = " ".join((ev.get("text") or "").split())
    return out


OPENCC_SCRIPT = r"""
import json, sys
from opencc import OpenCC
cc = OpenCC('s2tw')
sys.stdout.buffer.write(json.dumps([cc.convert(s) for s in json.loads(sys.stdin.buffer.read())],
                                   ensure_ascii=False).encode('utf-8'))
"""


def to_zh_tw(py: str, texts: list[str]) -> list[str] | None:
    """Simplified -> Traditional (Taiwan) with OpenCC('s2tw'), the conversion the page displays. This script runs under
    /usr/bin/python3, which has no opencc, so the conversion runs in the live venv (the harness's python, `py`).
    None when that python cannot convert (no opencc, or the call fails)."""
    try:
        out = subprocess.run([py, "-I", "-B", "-c", OPENCC_SCRIPT], input=json.dumps(texts, ensure_ascii=False).encode("utf-8"),
                             capture_output=True, timeout=60, check=True).stdout
        conv = json.loads(out.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return conv if isinstance(conv, list) and len(conv) == len(texts) else None


def flow_analysis(F: dict[str, Any], run_end_ms: float | None) -> dict[str, Any] | None:
    samples = F.get("samples") or []
    first = next((s for s in samples if s["segs"] >= 1), None)
    if first is None or run_end_ms is None:
        return None
    live = [s for s in samples if first["t"] <= s["t"] <= run_end_ms]
    # Per frame (F["fr"] = [t, graphemes shown], recorded in rAF): a frame is idle when its count did not grow since the
    # previous frame. Idle share is over frames; the longest idle run is from the last addition to the run's last idle frame.
    fr = [f for f in (F.get("fr") or []) if first["t"] <= f[0] <= run_end_ms]
    if len(live) < 3 or len(fr) < 3:
        return None
    span = 0.0
    adds: list[float] = []
    for a, b in zip(live, live[1:]):
        span += b["t"] - a["t"]
        if b["n"] > a["n"]:
            adds.append(b["t"])
    pairs = list(zip(fr, fr[1:]))
    idle_frames = longest_frames = run_frames = 0
    longest_ms = run_t0 = 0.0
    for a, b in pairs:
        if b[1] > a[1]:
            run_frames = 0
            continue
        if run_frames == 0:
            run_t0 = a[0]  # the frame where the last grapheme was added, before this idle run
        run_frames += 1
        idle_frames += 1
        if b[0] - run_t0 > longest_ms:
            longest_ms, longest_frames = b[0] - run_t0, run_frames
    gaps = [y - x for x, y in zip(adds, adds[1:])]
    empty = next((s for s in samples if s["t"] >= run_end_ms and s["q"] == 0 and s["bk"] == 0), None)
    frames = F.get("frames") or []
    frame_dts = [b - a for a, b in zip(frames, frames[1:]) if first["t"] <= a <= run_end_ms and b > a]
    fps = sorted(1000.0 / d for d in frame_dts)
    long_in = [d for t, d in (F.get("longtasks") or []) if first["t"] <= t <= run_end_ms]
    return {
        "span": span,
        "idle_frames": idle_frames,
        "frames_live": len(pairs),
        "idle_pct": 100.0 * idle_frames / len(pairs) if pairs else 0.0,
        "longest_idle_ms": longest_ms,
        "longest_idle_frames": longest_frames,
        "max_gap": max(gaps) if gaps else float("nan"),
        "gaps_250": sum(1 for g in gaps if g >= 250),
        "adds": len(adds),
        "lag_end": (empty["t"] - run_end_ms) if empty else None,
        "fps_median": statistics.median(fps) if fps else float("nan"),
        "fps_p5": fps[int(0.05 * (len(fps) - 1))] if fps else float("nan"),
        "frames": len(frame_dts),
        "longtasks": len(long_in),
        "longtask_max": max(long_in) if long_in else 0.0,
        "segments": live[-1]["segs"],
        "n_final": live[-1]["n"],
    }


def group_flow(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("flow")
    srv = h.serve(h.port, feeds, "flow")
    ctx = None
    try:
        before = h.feeds_now(feeds)
        ctx, page = new_ctx(browser, presets=preset("dark", "en"), extras=(FLOW_JS,))
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.5)  # the page is open before the run starts
        wait_mem("flow")
        h.start_replay(h.demo_src, feeds, 1, 30, "flow")
        path, run_id = h.new_run(feeds, before, "flow")
        run_end_ms = run_end_at(path, 150)
        empty = poll(lambda: page.evaluate(EMPTY_JS), 60, 0.1)
        time.sleep(0.3)
        F = page.evaluate("() => window.__nsFlow || {}")
        stats = page.evaluate("() => window.__nsliveReveal || {}")
        h.shot(page, "flow-1440-dark-en.png")
        an = flow_analysis(F, run_end_ms)
        if an is None:
            h.check("flow: live window measured", False, f"no samples (run_end seen: {run_end_ms is not None})")
            return
        h.check("flow: idle frames <= 5% of live frames (first segment -> run_end)", an["idle_pct"] <= 5.0,
                f"idle {an['idle_pct']:.1f}% ({an['idle_frames']} of {an['frames_live']} frames with no grapheme "
                f"added since the previous frame); longest idle run {an['longest_idle_ms']:.0f} ms over "
                f"{an['longest_idle_frames']} frames")
        h.check("flow: largest gap between visible additions < 250 ms", an["max_gap"] < 250,
                f"largest gap {an['max_gap']:.0f} ms; gaps >= 250 ms: {an['gaps_250']} of {max(an['adds'] - 1, 0)}")
        h.check("flow: queue empties after run_end", an["lag_end"] is not None and bool(empty),
                f"run_end -> queue empty {an['lag_end']} ms")
        info("flow: live window", f"span {an['span']:.0f} ms, segments {an['segments']}, additions {an['adds']}, "
                                  f"graphemes at run_end {an['n_final']}")
        info("flow: lag", f"run_end -> queue empty {an['lag_end']} ms; page maxLagMs {stats.get('maxLagMs')}, "
                          f"page maxGapMs {stats.get('maxGapMs')}, page idleMsWhileLive {stats.get('idleMsWhileLive')}")
        info("flow: FPS", f"rAF median {an['fps_median']:.1f}, p5 {an['fps_p5']:.1f} over {an['frames']} frames")
        info("flow: long tasks", f"{an['longtasks']} in the live window, max {an['longtask_max']:.0f} ms")
    finally:
        if ctx is not None:
            ctx.close()
        h.stop(srv)


def group_preroll(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("preroll")
    srv = h.serve(h.port, feeds, "preroll")
    ctxs: list[Any] = []
    try:
        before = h.feeds_now(feeds)
        url = h.url(h.port)
        pages: dict[str, Any] = {}
        for name, w, hgt, loc in PREROLL_SPECS:
            ctx, page = new_ctx(browser, w, hgt, presets=preset("dark", loc))
            ctxs.append(ctx)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            pages[name] = page
        time.sleep(1.5)
        wait_mem("preroll")
        t0 = time.time()
        h.start_replay(h.demo_src, feeds, 1, 30, "preroll")
        path, run_id = h.new_run(feeds, before, "preroll")
        state: dict[str, dict[str, Any]] = {
            name: {"pre": None, "terminal": False, "audio": False, "model": False, "device": False,
                   "seen_active": False, "last_pre_ids": None, "flip": None, "flip_t": None, "after": None,
                   "shot": False}
            for name in pages
        }
        deadline = time.time() + 120
        while time.time() < deadline and any(state[n]["after"] is None for n in pages):
            for name, page in pages.items():
                st = state[name]
                if st["after"] is not None:
                    continue
                snap = page.evaluate(SNAP_JS)
                now = time.time()
                if snap["preroll"] and st["pre"] is None:
                    st["pre"] = now
                if snap["terminal"]:
                    st["terminal"] = True
                for line in snap["lines"]:
                    if line["id"] == "audio" and AUDIO in line["text"]:
                        st["audio"] = True
                    if line["id"] == "model" and MODEL in line["text"]:
                        st["model"] = True
                    if line["id"] == "device":
                        st["device"] = True
                if snap["active"] is True:
                    st["seen_active"] = True
                    st["last_pre_ids"] = sorted({line["id"] for line in snap["lines"]})
                    if not st["shot"] and len(snap["lines"]) >= 2:
                        h.shot(page, f"preroll-{name}.png")
                        st["shot"] = True
                if st["seen_active"] and snap["active"] is False and st["flip"] is None:
                    st["flip"] = snap
                    st["flip_t"] = now
                    st["flip_ids"] = sorted({line["id"] for line in snap["lines"]})
                    # The stats are state, not rows: rows type in after the state is known, so read the run state.
                    st["flip_state"] = next((r for r in h.api_runs(h.port) if r.get("run_id") == run_id), {})
                if st["flip"] is not None and now - st["flip_t"] >= 3.0:
                    st["after"] = snap
            time.sleep(0.1)
        for name, page in pages.items():
            st = state[name]
            pre_t = st["pre"]
            rel = (lambda t: f"{t - t0:.2f} s after replay start") if pre_t is not None else (lambda t: "")
            h.check(f"preroll {name}: [data-testid=preroll] visible after run_start", pre_t is not None,
                    rel(pre_t) if pre_t is not None else "never visible")
            h.check(f"preroll {name}: terminal rows appear and name the audio file", st["terminal"] and st["audio"],
                    f"terminal visible {st['terminal']}; audio row contains '{AUDIO}': {st['audio']}; "
                    f"model row names '{MODEL}': {st['model']}; device row: {st['device']}")
            flip = st["flip"]
            flip_ids = st.get("flip_ids")
            fs = st.get("flip_state") or {}
            known = {"model": bool(fs.get("model")), "device": bool(fs.get("device")),
                     "language": bool(fs.get("detected_language")), "speakers": bool(fs.get("speakers"))}
            ok_known = bool(flip) and all(known.values())
            h.check(f"preroll {name}: at active->false model, device, language and speakers are all known (run state)",
                    ok_known,
                    (f"flip {st['flip_t'] - t0:.2f} s after replay start; server run state at flip {known}; "
                     f"summary keys {sorted(fs)[:14]}; terminal rows at flip {flip_ids}") if flip else
                    "active never flipped false")
            after = st["after"] or {}
            ok_after = bool(st["after"]) and after.get("stage") and after.get("transcript") and \
                after.get("prerollCount") == 0
            h.check(f"preroll {name}: full UI after transition (stage card, transcript, no pre-roll)", ok_after,
                    f"stage {after.get('stage')}, transcript {after.get('transcript')}, "
                    f"pre-roll nodes {after.get('prerollCount')}")
            if flip:
                info(f"preroll {name}: pre-roll length",
                     f"{st['flip_t'] - pre_t:.2f} s from first visible to active->false" if pre_t else "n/a")

        run_end_at(path, 150)  # the replay has finished (or its feed is complete)
        counts_bare: list[int] = []
        counts_run: list[int] = []
        ctx, page = new_ctx(browser, presets=preset("dark", "en"))
        ctxs.append(ctx)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        for _ in range(30):
            counts_bare.append(page.evaluate("() => document.querySelectorAll('[data-testid=\"preroll\"]').length"))
            time.sleep(0.1)
        bare_stage = page.evaluate("() => !!document.querySelector('[data-testid=\"stage-card\"]')")
        page.goto(url + f"?run={run_id}", wait_until="domcontentloaded", timeout=30000)
        for _ in range(30):
            counts_run.append(page.evaluate("() => document.querySelectorAll('[data-testid=\"preroll\"]').length"))
            time.sleep(0.1)
        h.check("preroll history: a finished run opened bare shows no pre-roll",
                max(counts_bare) == 0 and max(counts_bare) == 0,
                f"[data-testid=preroll] max count over 3 s: {max(counts_bare)}; stage card present: {bare_stage}")
        h.check("preroll history: ?run=<id> of a finished run shows no pre-roll", max(counts_run) == 0,
                f"[data-testid=preroll] max count over 3 s: {max(counts_run)}")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


def dismiss_run_complete(page: Any) -> None:
    """The run-complete dialog (run-complete-dialog.tsx) opens once when a live run finishes on the page. It is a modal
    AlertDialog: while open the page below takes no pointer events, so a click on a control waits on its overlay.
    Escape closes it, as a user would."""
    dialog = page.locator('[data-testid="run-complete-dialog"]')
    if dialog.count() and dialog.first.is_visible():
        page.keyboard.press("Escape")
        poll(lambda: not dialog.count() or not dialog.first.is_visible(), 3, 0.1)


def speed_control_body(h: Any, page: Any) -> None:
    sel = '[data-testid="speed-control"]'
    visible = poll(lambda: page.locator(sel).count() > 0 and page.locator(sel).first.is_visible(), 30, 0.3)
    h.check("speed: [data-testid=speed-control] visible on a live run", bool(visible),
            f"count {page.locator(sel).count()}")
    if not visible:
        return
    dismiss_run_complete(page)
    page.locator(sel).first.click(timeout=15000)
    dismiss_run_complete(page)
    page.locator('[data-testid="speed-mode-reading"]').click(timeout=15000)
    time.sleep(0.3)
    label_before = page.locator(sel).first.inner_text()
    stored_before = page.evaluate(SPEED_STATE_JS)
    page.reload(wait_until="domcontentloaded", timeout=30000)
    time.sleep(1.2)
    dismiss_run_complete(page)
    page.locator(sel).first.click(timeout=15000)
    checked = page.locator('[data-testid="speed-mode-reading"]').get_attribute("aria-checked")
    stored_after = page.evaluate(SPEED_STATE_JS)
    mode_after = json.loads(stored_after or "{}").get("mode")
    h.check("speed: reading mode persists across reload",
            checked == "true" and mode_after == "reading",
            f"stored before {stored_before}, after reload {stored_after}; speed-mode-reading aria-checked "
            f"{checked}; control label before {label_before!r}")
    cps0 = int(page.locator('[data-testid="speed-cps"]').inner_text())
    thumb = page.locator('[data-testid="speed-slider"] [role="slider"]').first
    dismiss_run_complete(page)
    thumb.focus()
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    time.sleep(0.3)
    stored_slider = json.loads(page.evaluate(SPEED_STATE_JS) or "{}")
    cps1 = int(page.locator('[data-testid="speed-cps"]').inner_text())
    h.check("speed: keyboard on the slider thumb sets a custom rate",
            stored_slider.get("mode") == "custom" and stored_slider.get("cps") == cps0 + 5 and cps1 == cps0 + 5,
            f"cps {cps0} -> {cps1} after 5 ArrowRight; stored {stored_slider}")
    page.reload(wait_until="domcontentloaded", timeout=30000)
    time.sleep(1.2)
    dismiss_run_complete(page)
    page.locator(sel).first.click(timeout=15000)
    cps2 = int(page.locator('[data-testid="speed-cps"]').inner_text())
    stored_reload = json.loads(page.evaluate(SPEED_STATE_JS) or "{}")
    h.check("speed: custom rate persists across reload",
            stored_reload.get("mode") == "custom" and cps2 == cps0 + 5,
            f"after reload cps {cps2}, stored {stored_reload}")
    info("speed: control label after the slider", page.locator(sel).first.inner_text())
    page.keyboard.press("Escape")


def seen_body(h: Any, page: Any, path: Path, label: str) -> None:
    ended = run_end_at(path, 90) is not None
    time.sleep(1.5)
    seen = page.evaluate("() => window.__nsSeen || {}")
    feed = feed_seg_texts(path)
    # The page shows zh-TW (OpenCC s2tw) where the feed is Simplified, so the expected text is the feed text converted
    # the same way, in the live venv. Without that conversion nothing can be compared and the check fails.
    keys = list(feed)
    conv = to_zh_tw(h.py, [feed[k] for k in keys])
    exp = dict(zip(keys, conv)) if conv is not None else {}
    full: list[str] = []
    partial: list[str] = []
    missing: list[str] = []
    for key, want in exp.items():
        if key not in seen:
            missing.append(key)
        elif " ".join(str(seen[key]["text"]).split()) == want:
            full.append(key)
        else:
            partial.append(key)
    h.check(f"{label}: new segments show their full text at first sight",
            bool(exp) and not partial and not missing,
            f"feed {len(feed)} segments (expected = feed text through OpenCC s2tw in {h.py}"
            f"{'' if conv is not None else ': conversion unavailable'}); "
            f"seen {len(seen)}; full at first sight {len(full)}; "
            f"partial {len(partial)} {[(k, ' '.join(str(seen[k]['text']).split())[:70], exp[k][:70]) for k in partial[:2]]}; "
            f"never seen {len(missing)}; run_end seen {ended}")


def easy_body(h: Any, page: Any, path: Path) -> None:
    time.sleep(2.0)
    count = page.locator('[data-testid="speed-control"]').count()
    h.check("easy view: no speed-control (count 0)", count == 0, f"speed-control count {count} on a live run")
    seen_body(h, page, path, "easy view")


def reduced_body(h: Any, page: Any, path: Path) -> None:
    time.sleep(2.0)
    count = page.locator('[data-testid="speed-control"]').count()
    h.check("reduced motion: no speed-control (count 0)", count == 0, f"speed-control count {count} on a live run")
    seen_body(h, page, path, "reduced motion")


def group_speed(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("speed")
    srv = h.serve(h.port, feeds, "speed")
    ctxs: list[Any] = []
    try:
        before = h.feeds_now(feeds)
        url = h.url(h.port)
        ctx_a, pa = new_ctx(browser, presets=preset("dark", "en"), extras=(SEEN_JS,))
        ctx_b, pb = new_ctx(browser, presets=preset("dark", "en", "1"), extras=(SEEN_JS,))
        ctx_c, pc = new_ctx(browser, presets=preset("dark", "en"), reduced=True, extras=(SEEN_JS,))
        ctxs = [ctx_a, ctx_b, ctx_c]
        for p in (pa, pb, pc):
            p.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.0)
        wait_mem("speed")
        h.start_replay(h.demo_src, feeds, 4, 2, "speed")
        path, run_id = h.new_run(feeds, before, "speed")
        h.scenario("speed control", speed_control_body, h, pa)
        h.scenario("easy view", easy_body, h, pb, path)
        h.scenario("reduced motion", reduced_body, h, pc, path)
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


def pre_metrics(page: Any, timeout: float) -> dict[str, Any]:
    end = time.time() + timeout
    while True:
        m = page.evaluate(OVERFLOW_JS)
        if m["pre"] or time.time() >= end:
            return m
        time.sleep(0.2)


def group_phone(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("phone")
    srv = h.serve(h.port, feeds, "phone")
    ctxs: list[Any] = []
    try:
        before = h.feeds_now(feeds)
        url = h.url(h.port)
        pages: list[tuple[str, Any]] = []
        for w in (360, 390, 430):
            for loc in ("en", "zh-TW"):
                ctx, page = new_ctx(browser, w, 800, presets=preset("dark", loc))
                ctxs.append(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                pages.append((f"{w}px-{loc}", page))
        time.sleep(1.5)
        wait_mem("phone")
        h.start_replay(h.demo_src, feeds, 2, 30, "phone")
        h.new_run(feeds, before, "phone")
        for name, page in pages:
            m = pre_metrics(page, 30)
            ok = m["pre"] and m["sw"] <= m["cw"]
            h.check(f"phone {name}: no horizontal overflow in the pre-roll (scrollWidth <= clientWidth)", bool(ok),
                    f"pre-roll shown {m['pre']}; documentElement scrollWidth {m['sw']} / clientWidth {m['cw']}; "
                    f"body {m['bsw']} / {m['bcw']}")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


GROUP_FUNCS = {"flow": group_flow, "preroll": group_preroll, "speed": group_speed, "phone": group_phone}


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, ux._exit_on_term)
    parser = argparse.ArgumentParser(description="Showreel checks for noScribe Live.")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=8930,
                        help="base port: flow +0, preroll +1, speed +2, phone +3")
    parser.add_argument("--static", default=str(ux.DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=ux.DEFAULT_PY, help="python with the server deps (live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs, src")
    args = parser.parse_args(argv)

    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        parser.error(f"unknown group(s) {unknown}; choose from {','.join(GROUPS)}")
    busy = [args.port + GROUP_PORT[g] for g in groups if ux.port_busy(args.port + GROUP_PORT[g])]
    if busy:
        print(f"FAIL setup: port(s) {busy} already in use; not touching those processes", flush=True)
        return 2
    if not (Path(args.static) / "index.html").is_file():
        print(f"NOTE: {args.static}/index.html is missing; the server serves its placeholder page", flush=True)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    h = ux.Harness(args)
    h.demo_src = h.src / ux.DEMO_NAME
    shutil.copyfile(FEED_SRC, h.demo_src)
    print(f"sources: {FEED_SRC.name} copied to {h.demo_src}", flush=True)
    try:
        wait_mem("browser launch")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()  # one browser for every group, run one after another
            try:
                for group in groups:
                    h.port = args.port + GROUP_PORT[group]
                    print(f"== group {group} (port {h.port})", flush=True)
                    try:
                        GROUP_FUNCS[group](h, browser)
                    except Exception as exc:
                        h.check(f"{group}: group completed", False, f"crashed: {exc!r}")
                    finally:
                        h.reap()
            finally:
                browser.close()
    finally:
        h.cleanup()
    return 0 if h.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
