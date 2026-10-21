#!/usr/bin/env python3
"""Nordic UI checks for noScribe Live: streaming, reduced motion, Easy view and zh-TW wording.

Groups (--only):
  stream    real-speed replay (speed 1, max-gap 3), page open before the run: __nsliveReveal lag, rAF FPS,
            long tasks, strict-prefix proof of streaming, full text at run_end, CLS; then a fresh open of the
            finished run (full text within 1 s, queued 0).
  reduced   reduced_motion=reduce: each new segment shows full text within 300 ms; no running animations.
  easy      dark/light x en/zh-TW with easy=1 preset: html[data-easy], paragraph font size, contrast, control
            sizes, animations, toggle label, easy-more; no streaming during a live run. Plus the toggle
            click and its persistence across a reload.
  zhterms   zh-TW: body.innerText contains none of the listed terms.
  export    token gate on (--token). A finished run: export-odt is enabled, the download is an .odt whose zip
            starts with a stored mimetype entry (application/vnd.oasis.opendocument.text) and whose content.xml
            names a speaker; the button then shows its success state. A live run: export-odt is not rendered until run_end, then appears enabled.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_nordic.py [--only stream,reduced,easy,zhterms,export] [--port 8800]
        [--static DIR] [--python PY] [--work DIR]

Ports: stream uses --port, reduced --port+1, easy --port+2, zhterms --port+3. export reuses --port+2 (it never
runs at the same time as easy: groups run one after another). Each group starts its own
`python -m server` and its own replay (`python -m server.replay SRC --speed N --max-gap S`) through the
Harness in test_ux.py. WORK (default /tmp/nslive-r9) holds src/ (a copy of the demo feed; the original is
read only), feeds/, logs/ and shots/. Exit code 0 only if every check passed. INFO lines carry measured
numbers that have no threshold.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import re
import os
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  shared harness: servers, replays, DOM helpers, check reporting

FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only
DEFAULT_WORK = Path("/tmp/nslive-r9")
GROUPS = ("stream", "reduced", "easy", "zhterms", "export")
GROUP_PORT = {"stream": 0, "reduced": 1, "easy": 2, "zhterms": 3, "export": 2}  # export shares easy's port
EXPORT_TOKEN = "nsexport-test-token"  # passed as --token; the server never logs it
ODT_MIME = "application/vnd.oasis.opendocument.text"
THEMES = ("dark", "light")
LOCALES = ("en", "zh-TW")
TOGGLE_LABEL = {"en": "Easy view", "zh-TW": "大字模式"}
TERMS = ("說話者", "運行", "文件", "信息", "默認", "加載", "屏幕", "用戶", "設置", "搜索", "菜單", "實時")

SAMPLE_JS = """() => {
  const now = performance.now();
  if (window.__nsPerf) window.__nsPerf.log.push({ t: now, k: 'eval' });
  const segs = {};
  for (const el of document.querySelectorAll('[data-segment-seq]')) {
    let txt = ''; const walk = (n) => { for (const c of n.childNodes) {
      if (c.nodeType === 3) txt += c.nodeValue; else if (c.nodeType === 1 && !c.hasAttribute('data-unrevealed')) walk(c); } };
    walk(el);
    segs[el.getAttribute('data-segment-seq')] = txt.trim();
  }
  const r = window.__nsliveReveal;
  return { t: now, segs, reveal: r ? { maxLagMs: r.maxLagMs, currentLagMs: r.currentLagMs,
                               queued: r.queued, revealedSegments: r.revealedSegments } : null };
}"""

# Installed before the app runs: rAF frame times, long tasks (>= 50 ms) and layout-shift sum.
PERF_JS = r"""
(() => {
  if (window.__nsPerf) return;
  // P.log: transcript scroller state (scrollTop, scrollHeight, clientHeight, data-following, segment count)
  // each time one of them changes, plus the harness's evaluate calls (kind 'eval', pushed by SAMPLE_JS).
  // Every time is performance.now(), the clock of LayoutShift startTime, so entries can be matched by frame.
  const P = { longtasks: [], frames: [], shifts: [], log: [] };
  window.__nsPerf = P;
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) P.longtasks.push([e.startTime, e.duration]); })
      .observe({ type: 'longtask', buffered: true });
  } catch (e) {}
  const rect = (r) => r ? [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] : null;
  const desc = (n) => {
    if (n && !n.tagName && n.parentElement) {
      const host = n.parentElement.closest('[data-index]');
      return 'text@' + n.parentElement.tagName.toLowerCase() + (host ? '#' + host.getAttribute('data-index') : '') + ':' + JSON.stringify(String(n.textContent).slice(0, 14));
    }
    if (!n || !n.tagName) return 'text';
    const cls = typeof n.className === 'string' ? n.className.split(' ').filter(Boolean).slice(0, 2).join('.') : '';
    const tid = n.getAttribute('data-testid'); const idx = n.getAttribute('data-index');
    return n.tagName.toLowerCase() + (tid ? '[' + tid + ']' : '') + (idx ? '#' + idx : '') + (cls ? '.' + cls : '');
  };
  // Every layout-shift entry, input-caused or not: value, startTime, hadRecentInput, and each source node with
  // its previousRect and currentRect (left, top, width, height). Python decides which ones count.
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) P.shifts.push({
      t: e.startTime, v: e.value, input: e.hadRecentInput, li: e.lastInputTime,
      src: (e.sources || []).map((s) => ({ d: desc(s.node), prev: rect(s.previousRect), cur: rect(s.currentRect) })) }); })
      .observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}
  let last = '';
  const tick = (t) => {
    P.frames.push(t);
    const sc = document.querySelector('[data-testid="transcript-scroll"]');
    const key = sc ? [sc.scrollTop, sc.scrollHeight, sc.clientHeight, sc.getAttribute('data-following'),
                      document.querySelectorAll('[data-segment-seq]').length].join('|') : 'none';
    if (key !== last) { last = key; P.log.push({ t: performance.now(), k: 'scroll', key }); }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""

PERF_READ_JS = """() => { const P = window.__nsPerf || { longtasks: [], frames: [], shifts: [], log: [] };
  return { longtasks: P.longtasks.slice(), frames: P.frames.slice(), shifts: P.shifts.slice(), log: P.log.slice() }; }"""

# Session-window CLS (the definition Chrome and web-vitals use): non-input shifts grouped into windows that end
# after a 1 s gap or after 5 s; the score is the largest window sum. The raw page-life sum is reported beside it.
CLS_GAP_MS = 1000.0
CLS_WINDOW_MS = 5000.0


def session_max(shifts: list[tuple[float, float]]) -> float:
    best = cur = 0.0
    start = prev = None
    for t, v in sorted(shifts):
        if start is None or t - prev > CLS_GAP_MS or t - start > CLS_WINDOW_MS:
            start, cur = t, 0.0
        cur += v
        prev = t
        best = max(best, cur)
    return best

ANIM_JS = """() => { const run = document.getAnimations().filter((a) => a.playState === 'running');
  const names = run.slice(0, 4).map((a) => { const t = a.effect && a.effect.target;
    const what = t ? t.tagName.toLowerCase() + (t.getAttribute('data-testid') ? '[' + t.getAttribute('data-testid') + ']' : '') : '?';
    return what + ':' + (a.animationName || a.transitionProperty || a.constructor.name); });
  return { count: run.length, names }; }"""

# Font sizes of visible transcript paragraphs; text and effective background colour of the newest one.
# The background is the nearest opaque ancestor colour; a translucent card falls back to the page background.
STYLE_JS = r"""() => {
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const ps = Array.from(document.querySelectorAll('[data-testid="paragraph"]'))
    .filter((p) => p.textContent.trim().length > 0 && p.getBoundingClientRect().height > 0);
  const out = { fonts: ps.map((p) => parseFloat(getComputedStyle(p).fontSize)), fg: null, bg: null,
                bgSource: 'none', translucent: false, paragraphs: ps.length };
  if (ps.length) {
    const p = ps[ps.length - 1];
    out.fg = parse(getComputedStyle(p).color);
    let el = p, nearest = null;
    while (el && !nearest) {
      const c = parse(getComputedStyle(el).backgroundColor);
      if (c && c.a > 0) {
        nearest = { c, name: el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : '') };
      }
      el = el.parentElement;
    }
    if (nearest && nearest.c.a >= 1) {
      out.bg = nearest.c; out.bgSource = nearest.name;
    } else {
      out.translucent = !!nearest;
      for (const n of [document.documentElement, document.body]) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c.a >= 1) {
          out.bg = c;
          out.bgSource = (nearest ? 'translucent ' + nearest.name + ' -> page ' : 'page ') + n.tagName.toLowerCase();
          break;
        }
      }
      if (!out.bg) out.bgSource = nearest ? 'translucent ' + nearest.name + ' (no opaque page bg)' : 'none';
    }
  }
  return out;
}"""

# Visible buttons, roles and inputs: size under 48x48. Per-block timeline buttons are excluded (pointer-events
# none); the timeline hit layer height is returned separately.
TARGETS_JS = """() => {
  const sel = 'button, [role="button"], input, select, textarea, [role="switch"], [role="checkbox"], [role="radio"], [role="tab"], [role="combobox"]';
  const small = [];
  let considered = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.hasAttribute('data-timeline-index')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) continue;
    considered += 1;
    if (r.width < 48 || r.height < 48) {
      const label = el.getAttribute('data-testid') || el.getAttribute('aria-label') || el.textContent.trim().slice(0, 24);
      small.push(el.tagName.toLowerCase() + ' ' + JSON.stringify(label) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
    }
  }
  const hit = document.querySelector('[data-testid="timeline-hit"]');
  return { considered, small, timelineHit: hit ? Math.round(hit.getBoundingClientRect().height) : null };
}"""


CJK_RE = re.compile(r"[\u3400-\u9fff]")

def same_text(shown: str, full: str) -> bool:
    """Equal text. The page shows zh-TW (opencc) where the feed is Simplified, so CJK text counts as equal when the
    lengths are within 2 characters. Other text must match exactly."""
    return shown == full or (bool(CJK_RE.search(full)) and abs(len(shown) - len(full)) <= 2)


def prefix_text(shown: str, full: str) -> bool:
    """A mid-stream state is a prefix of the final text; for CJK only the length bound (<= final + 2) can be checked."""
    return full.startswith(shown) or (bool(CJK_RE.search(full)) and len(shown) <= len(full) + 2)


def norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def feed_text(path: Path) -> dict[str, str]:
    """seq -> segment text as the feed wrote it (stripped). Lines still being written are skipped."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "segment":
            out[str(ev.get("seq"))] = str(ev.get("text") or "").strip()
    return out


def lum(c: dict[str, float]) -> float:
    def ch(v: float) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c["r"]) + 0.7152 * ch(c["g"]) + 0.0722 * ch(c["b"])


def contrast(fg: dict[str, float], bg: dict[str, float]) -> float:
    if fg["a"] < 1:  # composite the text colour over the background first
        a = fg["a"]
        fg = {"r": fg["r"] * a + bg["r"] * (1 - a), "g": fg["g"] * a + bg["g"] * (1 - a),
              "b": fg["b"] * a + bg["b"] * (1 - a), "a": 1.0}
    la, lb = lum(fg), lum(bg)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def rgba(c: dict[str, float] | None) -> str:
    if not c:
        return "none"
    return f"rgba({c['r']:.0f},{c['g']:.0f},{c['b']:.0f},{c['a']:.2f})"


def preset_js(theme: str, locale: str, easy: str | None) -> str:
    parts = [f"localStorage.setItem('noscribe-live-theme', {json.dumps(theme)});",
             f"localStorage.setItem('noscribe-live-locale', {json.dumps(locale)});"]
    if easy is not None:
        parts.append(f"localStorage.setItem('noscribe-live-easy', {json.dumps(easy)});")
    return "try { " + " ".join(parts) + " } catch (e) {}"


def new_ctx(browser: Any, presets: str | None = None) -> tuple[Any, Any]:
    ctx = browser.new_context(viewport=ux.VIEWPORT)
    ctx.add_init_script(ux.INIT_JS)
    if presets:
        ctx.add_init_script(presets)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    return ctx, page


# ---- stream -----------------------------------------------------------------------------------------
def cls_report(h: Any, perf: dict[str, Any], first_t: float | None, end_t: float | None, reloaded: bool) -> None:
    """Layout-shift evidence for the stream group, on the page clock (performance.now, the clock of LayoutShift
    startTime). The metric is the session-window CLS (Chrome's definition) over non-input shifts from the first
    segment on screen to run_end; the raw page-life sum is printed beside it for comparison. Inside that window the
    harness does no scroll, click or reload: its only calls are the sampling evaluates (kind 'eval' in the log).
    Each shift is matched with the scroller log (st|sh|ch|follow|segs) for a scrollTop change within one frame
    (the follow-scroll) and for the number of segments revealed in the same frame (bursts)."""
    shifts = perf.get("shifts", [])
    log = perf.get("log", [])
    lo = float(first_t) if first_t is not None else float("-inf")
    hi = float(end_t) if end_t is not None else float("inf")
    raw = [s for s in shifts if not s.get("input")]
    win = [s for s in raw if lo <= float(s.get("t") or 0) <= hi]
    cls_win = session_max([(float(s["t"]), float(s["v"])) for s in win])
    cls_all = session_max([(float(s["t"]), float(s["v"])) for s in raw])
    sum_win = sum(float(s["v"]) for s in win)
    sum_all = sum(float(s["v"]) for s in raw)
    print(f"INFO stream CLS window {lo:.0f}-{hi:.0f} ms (page clock): session-window max {cls_win:.4f}, raw sum "
          f"{sum_win:.4f} over {len(win)} shifts; page life: session max {cls_all:.4f}, raw sum {sum_all:.4f} over "
          f"{len(raw)} shifts; input-caused {len(shifts) - len(raw)} excluded; reloaded {reloaded}", flush=True)

    scroll = [(float(e["t"]), str(e.get("key", "")).split("|")) for e in log if e.get("k") == "scroll"]

    def state_at(t: float) -> str:
        last = "none"
        for ts, parts in scroll:
            if ts > t:
                break
            last = "|".join(parts)
        return last

    st_changes = [ts for (_, prev), (ts, cur) in zip(scroll, scroll[1:]) if cur[0] != prev[0]]
    near = 70.0  # ms: one 60 fps frame plus slack
    with_st = sum(1 for s in win if any(abs(c - float(s["t"])) <= near for c in st_changes))
    harness = [e for e in log if e.get("k") not in ("eval", "scroll") and lo <= float(e.get("t") or 0) <= hi]
    steps = [int(cur[4]) - int(prev[4]) for (_, prev), (ts, cur) in zip(scroll, scroll[1:])
             if lo <= ts <= hi and cur[4] != prev[4]]
    print(f"INFO stream attribution in window: (a) harness non-evaluate actions {len(harness)}; (b) shifts with a "
          f"scrollTop change within {near:.0f} ms {with_st}/{len(win)}; (c) frames with a segment-count step "
          f"{len(steps)}, of which >= 2 segments {sum(1 for k in steps if k >= 2)} (max {max(steps) if steps else 0}); "
          f"scrollTop changes in window {sum(1 for ts in st_changes if lo <= ts <= hi)}", flush=True)

    agg: dict[str, list[float]] = {}
    for s in win:
        for src in s.get("src") or []:
            prev, cur = src.get("prev"), src.get("cur")
            dy = float(cur[1]) - float(prev[1]) if cur and prev else 0.0
            way = "down" if dy > 0.5 else ("up" if dy < -0.5 else "flat")
            acc = agg.setdefault(f"{src.get('d')} {way}", [0, 0.0, 0.0])
            acc[0] += 1
            acc[1] += float(s["v"])
            acc[2] += dy
    top = sorted(agg.items(), key=lambda kv: -kv[1][1])[:8]
    print("INFO stream CLS sources in window (node and direction: rects, summed value, mean dy px): " +
          ("; ".join(f"{k} n={v[0]} sum={v[1]:.4f} mean_dy={v[2] / v[0]:+.1f}" for k, v in top) or "none"), flush=True)
    for s in win[:int(os.environ.get("NS_SRC_DUMP", "0"))]:
        where = "; ".join(f"{x.get('d')} prev {x.get('prev')} cur {x.get('cur')}" for x in s.get("src") or [])
        print(f"INFO shift t={float(s['t']):.1f} v={float(s['v']):.4f} scroller {state_at(float(s['t']))} | {where}",
              flush=True)
    h.check("stream: layout-shift CLS (session-window max, first segment to run_end) <= 0.1", cls_win <= 0.1,
            f"CLS {cls_win:.4f} (raw sum {sum_win:.4f} over {len(win)} shifts); page-life session max {cls_all:.4f}")


def stream_body(h: Any, page: Any, path: Path, run_id: str) -> None:
    reloaded = False
    # The demo's first segment lands 10.6 s into a replay at --speed 2 --max-gap 2, and 19.3 s at --speed 1 --max-gap 3
    # (the stream group's settings). An 8 s wait reloaded a page that was already following the run live.
    ready = ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.2)
    if not ready:  # the page did not pick up the new run on its own; load it now
        page.reload(wait_until="domcontentloaded")
        reloaded = True
        ready = ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.2)
    h.check("stream setup: page shows the live run (>= 1 segment)", bool(ready),
            f"segments {ux.seg_count(page)}, reloaded after run start {reloaded}")

    samples: list[dict[str, Any]] = []
    partial: dict[str, str] = {}
    mismatches = 0
    mismatch_ex: list[str] = []
    seen_end = None
    end_t = None  # page clock (performance.now) when run_end first showed on the page
    first_t = None  # page clock when the first segment was on screen: the CLS window starts here
    drained_at = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 150:
        snap = page.evaluate(SAMPLE_JS)
        if first_t is None and snap.get("segs"):
            first_t = snap.get("t")
        if snap.get("reveal"):
            samples.append(snap["reveal"])
        final = feed_text(path)
        for seq, raw in snap.get("segs", {}).items():
            shown, full = norm(raw), norm(final.get(seq, ""))
            if not shown or not full or same_text(shown, full):
                continue
            if prefix_text(shown, full):
                partial.setdefault(seq, f"{shown[:18]!r} of {full[:18]!r}...")
            else:
                mismatches += 1
                if not mismatch_ex:
                    i = next((j for j, (a, b) in enumerate(zip(shown, full)) if a != b), min(len(shown), len(full)))
                    mismatch_ex.append(f"seq {seq} at char {i}: shown {shown[max(0, i - 8):i + 8]!r} "
                                       f"vs final {full[max(0, i - 8):i + 8]!r}")
        if seen_end is None and ux.page_ended(page, run_id):
            seen_end = time.monotonic()
            end_t = snap.get("t")
        if seen_end is not None:
            complete = bool(final) and all(same_text(norm(snap.get("segs", {}).get(seq, "")), norm(t))
                                           for seq, t in final.items())
            if complete and drained_at is None:
                drained_at = time.monotonic() - seen_end
            if drained_at is not None or time.monotonic() - seen_end > 12:
                break
        time.sleep(0.1)

    final = feed_text(path)
    snap = page.evaluate(SAMPLE_JS)
    rendered = {seq: norm(raw) for seq, raw in snap.get("segs", {}).items()}
    full_ok = sum(1 for seq, text in final.items() if same_text(rendered.get(seq, ""), norm(text)))
    rv = snap.get("reveal") or {}
    max_page = max((float(s.get("maxLagMs") or 0) for s in samples), default=0.0)
    cur = sorted(float(s.get("currentLagMs") or 0) for s in samples)
    p95 = cur[int(0.95 * (len(cur) - 1))] if cur else 0.0
    max_cur = cur[-1] if cur else 0.0
    h.check("stream: maxLagMs <= 1500 (__nsliveReveal sampled every 100 ms)",
            bool(samples) and max_page <= 1500,
            f"maxLagMs {max_page:.0f}, currentLagMs max {max_cur:.0f} p95 {p95:.0f}, samples {len(samples)}")
    h.check("stream: a segment is seen as a strict prefix of its final text mid-stream",
            bool(partial) and mismatches == 0,
            f"{len(partial)} segments seen partial, non-prefix states {mismatches}, "
            f"e.g. {next(iter(partial.values()), None)}, first non-prefix {mismatch_ex[0] if mismatch_ex else None}")
    drain = (f"full text complete {drained_at:.2f} s after run_end" if drained_at is not None
             else "full text NOT complete 12 s after run_end")
    h.check("stream: at run_end all segments show full text and queued is 0",
            bool(seen_end) and full_ok == len(final) and len(rendered) == len(final) and rv.get("queued") == 0,
            f"run_end seen {bool(seen_end)}, {drain}, full {full_ok}/{len(final)}, rendered {len(rendered)}, "
            f"queued {rv.get('queued')}, revealedSegments {rv.get('revealedSegments')}")

    perf = page.evaluate(PERF_READ_JS)
    frames = perf.get("frames", [])
    windows: list[int] = []
    if len(frames) > 1:
        f0 = frames[0]
        counts: dict[int, int] = {}
        for t in frames:
            k = int((t - f0) // 1000)
            counts[k] = counts.get(k, 0) + 1
        keys = sorted(counts)
        windows = [counts[k] for k in keys[:-1]] or [counts[keys[0]]]  # drop the last, partial second
    med = statistics.median(windows) if windows else float("nan")
    p5 = sorted(windows)[int(0.05 * (len(windows) - 1))] if windows else float("nan")
    lts = [float(dur) for _start, dur in perf.get("longtasks", [])]  # PERF_JS keeps [startTime, duration]
    print(f"INFO stream FPS (rAF frames per 1 s window, {len(windows)} windows): median {med:.0f}, p5 {p5:.0f}",
          flush=True)
    print(f"INFO stream long tasks since page load: count {len(lts)}, max {max(lts) if lts else 0:.0f} ms, "
          f"total {sum(lts):.0f} ms", flush=True)
    cls_report(h, perf, first_t, end_t, reloaded)
    h.shot(page, "stream-end.png")


def finished_body(h: Any, browser: Any, path: Path, run_id: str) -> None:
    final = feed_text(path)
    ctx, page = new_ctx(browser)
    try:
        t0 = time.monotonic()
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        done_at = None
        rendered: dict[str, str] = {}
        while time.monotonic() - t0 < 5:
            snap = page.evaluate(SAMPLE_JS)
            rendered = {seq: norm(raw) for seq, raw in snap.get("segs", {}).items()}
            if len(rendered) >= len(final) and all(rendered.get(seq) == norm(t) for seq, t in final.items()):
                done_at = time.monotonic() - t0
                break
            time.sleep(0.05)
        rv = (page.evaluate(SAMPLE_JS) or {}).get("reveal") or {}
        took = "never" if done_at is None else f"{done_at:.2f} s"
        h.check("stream finished run (fresh open): all segments full text within 1 s, queued 0",
                done_at is not None and done_at <= 1.0 and rv.get("queued") == 0,
                f"full text after {took} for {len(final)} segments, rendered {len(rendered)}, "
                f"queued {rv.get('queued')}, revealedSegments {rv.get('revealedSegments')}")
        h.shot(page, "stream-finished-open.png")
    finally:
        ctx.close()


def group_stream(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("stream")
    srv = h.serve(h.port, feeds, "stream")
    try:
        before = h.feeds_now(feeds)
        ctx, page = h.new_page(browser, extra=PERF_JS)
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            # Harness actions are logged on the page clock so the CLS window can be attributed (see cls_report).
            page.evaluate("() => window.__nsPerf && window.__nsPerf.log.push({ t: performance.now(), k: 'goto' })")
            time.sleep(1.0)  # the page is open before the run starts
            h.start_replay(h.demo_src, feeds, 1, 3, "stream")
            path, run_id = h.new_run(feeds, before, "stream")
            h.scenario("stream", stream_body, h, page, path, run_id)
            h.scenario("stream finished run", finished_body, h, browser, path, run_id)
        finally:
            ctx.close()
    finally:
        h.stop(srv)


# ---- reduced ----------------------------------------------------------------------------------------
def reduced_body(h: Any, browser: Any, feeds: Path) -> None:
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, 2, 2, "reduced")
    path, run_id = h.new_run(feeds, before, "reduced")
    ctx, page = h.new_page(browser, reduced=True, recorders=True)
    try:
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.page_ended(page, run_id), 90, 0.5)
        expect = feed_text(path)
        ux.wait_until(lambda: ux.seg_count(page) >= len(expect), 10, 0.3)
        rec = page.evaluate("() => window.__nsSegRec || {}")
        problems: list[str] = []
        worst = 0.0
        for seq, text in expect.items():
            r = rec.get(seq)
            if r is None:
                problems.append(f"seq {seq} never rendered")
                continue
            full = next((t for t, n in r["log"] if abs(n - len(text)) <= 2), None)
            if full is None:
                problems.append(f"seq {seq} never reached {len(text)} chars")
                continue
            delay = full - r["appear"]
            worst = max(worst, delay)
            if delay > 300:
                problems.append(f"seq {seq} took {delay:.0f} ms")
        rendered = ux.seg_count(page)
        example = f", e.g. {problems[0]}" if problems else ""
        h.check("reduced: each new segment shows its full text within 300 ms of appearing",
                bool(expect) and not problems and rendered == len(expect),
                f"feed {len(expect)} segments, rendered {rendered}, worst delay {worst:.0f} ms, "
                f"problems {len(problems)}{example}")
        time.sleep(1.0)  # settle
        an = page.evaluate(ANIM_JS)
        h.check("reduced: no running animations after settle (document.getAnimations)", an["count"] == 0,
                f"running {an['count']} {an['names']}")
        h.shot(page, "reduced-end.png")
    finally:
        ctx.close()


def group_reduced(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("reduced")
    srv = h.serve(h.port, feeds, "reduced")
    try:
        h.scenario("reduced motion", reduced_body, h, browser, feeds)
    finally:
        h.stop(srv)


# ---- easy -------------------------------------------------------------------------------------------
def easy_case_body(h: Any, page: Any, theme: str, locale: str) -> None:
    tag = f"{theme}/{locale}"
    ready = ux.wait_until(lambda: ux.seg_count(page) >= 3, 60, 0.2)
    if not ready:
        h.check(f"easy {tag}: segments rendered", False, f"segments {ux.seg_count(page)}")
        return
    time.sleep(0.6)  # first paints and transitions settle
    state = page.evaluate("() => [document.documentElement.getAttribute('data-easy'), "
                          "document.documentElement.getAttribute('data-theme')]")
    h.check(f"easy {tag}: html[data-easy=true] and data-theme {theme}", state == ["true", theme],
            f"data-easy/data-theme {state}")

    st = page.evaluate(STYLE_JS)
    fonts = st["fonts"]
    min_font = min(fonts) if fonts else 0.0
    h.check(f"easy {tag}: transcript paragraph font-size >= 22 px", bool(fonts) and min_font >= 22,
            f"{len(fonts)} paragraphs, min {min_font:.1f} px, max {max(fonts) if fonts else 0:.1f} px")

    fg, bg = st["fg"], st["bg"]
    if fg and bg:
        ratio = contrast(fg, bg)
        detail = (f"ratio {ratio:.2f}:1, text {rgba(fg)}, background {rgba(bg)} from {st['bgSource']}"
                  f"{' (card translucent: page background used)' if st['translucent'] else ''}")
        h.check(f"easy {tag}: body text contrast >= 7:1", ratio >= 7, detail)
    else:
        h.check(f"easy {tag}: body text contrast >= 7:1", False,
                f"colour not determinable: text {rgba(fg)}, background source {st['bgSource']}")

    tg = page.evaluate(TARGETS_JS)
    hit = tg.get("timelineHit")
    h.check(f"easy {tag}: visible controls >= 48x48 (timeline hit layer {hit} px tall)",
            not tg["small"] and hit is not None and hit >= 48,
            f"{tg['considered']} visible controls, {len(tg['small'])} under 48 px: {tg['small'][:5]}")

    an = page.evaluate(ANIM_JS)
    h.check(f"easy {tag}: document.getAnimations() running count 0 (mid-run)", an["count"] == 0,
            f"running {an['count']} {an['names']}")

    label = (page.locator('[data-testid="easy-toggle"]').first.text_content(timeout=5000) or "").strip()
    want = TOGGLE_LABEL[locale]
    h.check(f"easy {tag}: toggle label {want!r}", label == want, f"label {label!r}")

    more = page.locator('[data-testid="easy-more"]')
    count = more.count()
    before_state = after_state = None
    error = ""
    if count:
        try:
            before_state = more.first.get_attribute("aria-expanded")
            more.first.click(timeout=5000)
            time.sleep(0.3)
            after_state = more.first.get_attribute("aria-expanded")
            more.first.click(timeout=5000)  # restore
            time.sleep(0.2)
        except Exception as exc:
            error = f", click failed: {type(exc).__name__}"
    h.check(f"easy {tag}: easy-more disclosure toggles", count > 0 and before_state != after_state,
            f"count {count}, aria-expanded {before_state!r} -> {after_state!r}{error}")
    h.shot(page, f"easy-{theme}-{locale}.png")


def easy_watch_body(h: Any, cases: list[Any], path: Path, run_id: str) -> None:
    """Round-robin over the four live pages until run_end on each: queued and partial text must stay clear."""
    keys = [f"{t}/{l}" for t, l, _c, _p in cases]
    queued_max = {k: 0 for k in keys}
    partial: dict[str, set[str]] = {k: set() for k in keys}
    ended = {k: False for k in keys}
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120 and not all(ended.values()):
        final = feed_text(path)
        for (_t, _l, _c, page), k in zip(cases, keys):
            snap = page.evaluate(SAMPLE_JS)
            rv = snap.get("reveal") or {}
            queued_max[k] = max(queued_max[k], int(rv.get("queued") or 0))
            for seq, raw in snap.get("segs", {}).items():
                shown, full = norm(raw), norm(final.get(seq, ""))
                if shown and full and shown != full and full.startswith(shown):
                    partial[k].add(seq)
            if not ended[k] and ux.page_ended(page, run_id):
                ended[k] = True
        time.sleep(0.1)
    time.sleep(1.0)
    final = feed_text(path)
    for (_t, _l, _c, page), k in zip(cases, keys):
        snap = page.evaluate(SAMPLE_JS)
        rendered = {seq: norm(raw) for seq, raw in snap.get("segs", {}).items()}
        full_ok = sum(1 for seq, text in final.items() if same_text(rendered.get(seq, ""), norm(text)))
        h.check(f"easy {k}: live segments appear with full text, no streaming (queued stays 0)",
                ended[k] and queued_max[k] == 0 and not partial[k] and full_ok == len(final),
                f"run_end seen {ended[k]}, max queued {queued_max[k]}, partial seqs {len(partial[k])}, "
                f"full text {full_ok}/{len(final)}")
        an = page.evaluate(ANIM_JS)
        h.check(f"easy {k}: document.getAnimations() running count 0 after run_end", an["count"] == 0,
                f"running {an['count']} {an['names']}")


def easy_toggle_body(h: Any, browser: Any) -> None:
    ctx, page = new_ctx(browser, preset_js("dark", "en", None))
    try:
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.3)
        attr = "() => document.documentElement.getAttribute('data-easy')"
        toggle = page.locator('[data-testid="easy-toggle"]').first
        start = page.evaluate(attr)
        toggle.click(timeout=5000)
        time.sleep(0.3)
        on = page.evaluate(attr)
        stored = page.evaluate("() => localStorage.getItem('noscribe-live-easy')")
        pressed = toggle.get_attribute("aria-pressed")
        h.check("easy toggle: click turns easy view on (data-easy, aria-pressed true, localStorage 1)",
                start is None and on == "true" and stored == "1" and pressed == "true",
                f"before {start!r}, after click {on!r}, localStorage {stored!r}, aria-pressed {pressed!r}")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.3)
        after = page.evaluate(attr)
        pressed2 = page.locator('[data-testid="easy-toggle"]').first.get_attribute("aria-pressed")
        h.check("easy toggle: reload keeps easy view on", after == "true" and pressed2 == "true",
                f"data-easy after reload {after!r}, aria-pressed {pressed2!r}")
        page.locator('[data-testid="easy-toggle"]').first.click(timeout=5000)
        time.sleep(0.3)
        off = page.evaluate(attr)
        stored2 = page.evaluate("() => localStorage.getItem('noscribe-live-easy')")
        h.check("easy toggle: second click turns it off (data-easy removed, localStorage 0)",
                off is None and stored2 == "0", f"data-easy {off!r}, localStorage {stored2!r}")
    finally:
        ctx.close()


EASY_TIMELINE_JS = """() => {
  const card = document.querySelector('[data-testid="timeline-card"]');
  if (!card) return null;
  const cs = getComputedStyle(card);
  const edge = card.getBoundingClientRect().right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
  const rights = Array.from(card.querySelectorAll('[data-timeline-index]')).map((b) => b.getBoundingClientRect().right);
  const hit = card.querySelector('[data-testid="timeline-hit"]');
  const hitRight = hit ? hit.getBoundingClientRect().right : null;
  const maxRight = Math.max(hitRight ?? -Infinity, ...rights);
  const root = document.documentElement;
  return { edge, blocks: rights.length, hit: hitRight !== null, hitRight, maxRight: Number.isFinite(maxRight) ? maxRight : null,
           scrollWidth: root.scrollWidth, clientWidth: root.clientWidth }; }"""


def easy_timeline_body(h: Any, browser: Any, run_id: str) -> None:
    """Easy view on a finished run at 1440x900: timeline blocks and the hit layer stay inside the timeline card."""
    ux.wait_until(lambda: h.api_status(h.port, run_id) == "finished", 60, 0.5)
    for theme in THEMES:
        tag = f"{theme}/en"
        ctx, page = new_ctx(browser, preset_js(theme, "en", "1"))
        try:
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.3)
            m: dict[str, Any] = {}

            def measured() -> bool:
                m.clear()
                m.update(page.evaluate(EASY_TIMELINE_JS) or {})
                return m.get("blocks", 0) > 0

            ux.wait_until(measured, 15, 0.3)
            edge, max_right = m.get("edge"), m.get("maxRight")
            fits = (m.get("blocks", 0) > 0 and bool(m.get("hit")) and edge is not None and max_right is not None
                    and max_right <= edge + 0.5)
            print(f"  easy timeline {tag}: max right edge {max_right} vs card edge {edge} "
                  f"(blocks {m.get('blocks')}, hit layer right {m.get('hitRight')})", flush=True)
            h.check(f"easy timeline {tag} at 1440x900: every timeline block and the hit layer end inside the card",
                    fits, f"max right edge {max_right} vs card edge {edge}, blocks {m.get('blocks')}, "
                          f"hit layer {m.get('hit')}")
            sw, cw = m.get("scrollWidth"), m.get("clientWidth")
            h.check(f"easy timeline {tag} at 1440x900: documentElement.scrollWidth <= clientWidth",
                    sw is not None and cw is not None and sw <= cw, f"scrollWidth {sw}, clientWidth {cw}")
        finally:
            ctx.close()


def group_easy(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("easy")
    srv = h.serve(h.port, feeds, "easy")
    cases: list[Any] = []
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 1.2, 2, "easy")
        path, run_id = h.new_run(feeds, before, "easy")
        for theme in THEMES:
            for locale in LOCALES:
                ctx, page = new_ctx(browser, preset_js(theme, locale, "1"))
                cases.append((theme, locale, ctx, page))
                page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        for theme, locale, _ctx, page in cases:
            h.scenario(f"easy {theme}/{locale}", easy_case_body, h, page, theme, locale)
        h.scenario("easy live run", easy_watch_body, h, cases, path, run_id)
        h.scenario("easy timeline 1440", easy_timeline_body, h, browser, run_id)
        h.scenario("easy toggle", easy_toggle_body, h, browser)
    finally:
        for _t, _l, ctx, _p in cases:
            ctx.close()
        h.stop(srv)


# ---- zhterms ----------------------------------------------------------------------------------------
# ---- export -----------------------------------------------------------------------------------------
def token_server(h: Any, port: int, feeds: Path, tag: str) -> Any:
    """`python -m server --token` (the token gate on). ux.Harness.serve() sends no token, so it is not used here."""
    proc = h._spawn([h.py, "-m", "server", "--port", str(port), "--feeds", str(feeds), "--static", str(h.static),
                     "--token", EXPORT_TOKEN], f"server-{tag}-{port}.log")

    def health() -> bool:
        req = urllib.request.Request(f"{h.url(port)}api/health", headers={"Authorization": f"Bearer {EXPORT_TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    if not ux.wait_until(health, 20):
        raise RuntimeError(f"token server on port {port} did not answer /api/health with the token (logs in {h.logs})")
    return proc


def export_finished_body(h: Any, browser: Any, port: int) -> None:
    try:
        urllib.request.urlopen(f"{h.url(port)}api/runs", timeout=2)
        code = 200
    except urllib.error.HTTPError as exc:
        code = exc.code
    h.check("export: token gate refuses API calls without the token", code == 401, f"GET api/runs without token -> {code}")
    ctx = browser.new_context(viewport=ux.VIEWPORT, accept_downloads=True)
    ctx.add_init_script(ux.INIT_JS)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    try:
        page.goto(f"{h.url(port)}?token={EXPORT_TOKEN}", wait_until="domcontentloaded", timeout=30000)
        shown = ux.wait_until(lambda: ux.seg_count(page) >= 1, 30, 0.3)
        btn = page.locator('[data-testid="export-odt"]').first
        btn.wait_for(state="visible", timeout=15000)
        enabled = btn.is_enabled()
        h.check("export finished run: export-odt visible and enabled", bool(shown) and enabled,
                f"segments {ux.seg_count(page)}, enabled {enabled}, data-state {btn.get_attribute('data-state')!r}")
        with page.expect_download(timeout=60000) as info:
            btn.click(timeout=5000)
        dl = info.value
        name = Path(dl.suggested_filename).name
        out_dir = Path(tempfile.mkdtemp(prefix="odt-", dir=str(h.work)))  # a new, empty directory for the download
        target = out_dir / name
        dl.save_as(str(target))
        h.check("export: download filename ends with .odt", name.endswith(".odt"), f"suggested filename {name!r}")
        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            first = zf.infolist()[0] if names else None
            mime = zf.read("mimetype").decode("ascii", "replace") if "mimetype" in names else None
            xml = zf.read("content.xml").decode("utf-8", "replace") if "content.xml" in names else ""
        h.check("export: zip's first entry is a stored mimetype = application/vnd.oasis.opendocument.text",
                first is not None and first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
                and mime == ODT_MIME,
                f"entries {names[:4]}, first {first.filename if first else None!r}, compress "
                f"{first.compress_type if first else None}, mimetype {mime!r}")
        labels = [lab for lab in ("Speaker 1", "Speaker 2", "說話者 1", "說話者 2") if lab in xml]
        h.check("export: content.xml names a speaker", bool(labels), f"labels {labels}, content.xml {len(xml)} bytes")

        def success() -> str | None:  # data-state="success" when the page sets it, else the localised text
            if btn.get_attribute("data-state") == "success":
                return "data-state=success"
            body = page.evaluate("() => document.body.innerText") or ""
            if "Downloaded" in body or "已下載" in body:
                return "Downloaded text on the page"
            return None

        how = ux.wait_until(success, 8, 0.2)
        h.check("export finished run: button shows its success state after the download", bool(how),
                f"{how or 'no success state'}; data-state {btn.get_attribute('data-state')!r}, "
                f"label {(btn.text_content() or '').strip()!r}")
        h.shot(page, "export-finished.png")
    finally:
        ctx.close()


def export_live_body(h: Any, browser: Any, port: int, run_id: str) -> None:
    ctx = browser.new_context(viewport=ux.VIEWPORT)
    ctx.add_init_script(ux.INIT_JS)
    page = ctx.new_page()
    try:
        page.goto(f"{h.url(port)}?token={EXPORT_TOKEN}", wait_until="domcontentloaded", timeout=30000)
        shown = ux.wait_until(lambda: ux.seg_count(page) >= 1, 60, 0.3)
        # The replay runs at speed 1, so the run stays live for minutes: check right after the first segment renders.
        seen_end = ux.page_ended(page, run_id)
        export = page.locator('[data-testid="export-odt"]')
        live_count = export.count()
        h.check("export live run: export-odt not rendered while the run is live",
                bool(shown) and not seen_end and live_count == 0,
                f"segments {ux.seg_count(page)}, run_end seen {seen_end}, export-odt count {live_count}")
        h.shot(page, "export-live.png")
        # After run_end the button appears, enabled.
        ended = ux.wait_until(lambda: ux.page_ended(page, run_id), 400, 0.5)
        appeared = ux.wait_until(lambda: export.count() == 1, 15, 0.3)
        enabled = bool(appeared) and export.first.is_enabled()
        state = export.first.get_attribute("data-state") if appeared else None
        h.check("export live run: export-odt appears (count 1) and enabled after run_end",
                bool(ended) and bool(appeared) and enabled,
                f"run_end seen {bool(ended)}, export-odt count {export.count()}, enabled {enabled}, data-state {state!r}")
    finally:
        ctx.close()


def group_export(h: Any, browser: Any) -> None:
    port = h.port
    feeds = h.new_feeds("export-finished")
    shutil.copyfile(FEED_SRC, feeds / FEED_SRC.name)  # a complete run: run_start to run_end in one file
    srv = token_server(h, port, feeds, "export-finished")
    try:
        h.scenario("export finished run", export_finished_body, h, browser, port)
    finally:
        h.stop(srv)
    feeds = h.new_feeds("export-live")
    srv = token_server(h, port, feeds, "export-live")
    replay = None
    try:
        before = h.feeds_now(feeds)
        replay = h.start_replay(h.demo_src, feeds, 1, 2, "export-live")
        _path, run_id = h.new_run(feeds, before, "export-live")
        h.scenario("export live run", export_live_body, h, browser, port, run_id)
    finally:
        h.stop(replay)
        h.stop(srv)


def zhterms_body(h: Any, page: Any, path: Path, run_id: str) -> None:
    ended = ux.wait_until(lambda: ux.page_ended(page, run_id), 90, 0.3)
    time.sleep(0.5)
    text = page.evaluate("() => document.body.innerText")
    lang = page.evaluate("() => document.documentElement.lang")
    h.check("zhterms: zh-TW is active (Easy view label 大字模式 on the page)", "大字模式" in text,
            f"html lang {lang!r}, run_end seen {bool(ended)}")
    content = " ".join(feed_text(path).values())
    hits = [f"{term} x{text.count(term)} (transcript text has {content.count(term)})"
            for term in TERMS if term in text]
    h.check("zhterms: zh-TW document.body.innerText contains none of the 12 listed terms", not hits,
            f"hits {hits or 'none'}")
    h.shot(page, "zhterms-zh-tw.png")


def group_zhterms(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("zhterms")
    srv = h.serve(h.port, feeds, "zhterms")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 4, 2, "zhterms")
        path, run_id = h.new_run(feeds, before, "zhterms")
        ctx, page = new_ctx(browser, preset_js("dark", "zh-TW", None))
        try:
            page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
            h.scenario("zhterms", zhterms_body, h, page, path, run_id)
        finally:
            ctx.close()
    finally:
        h.stop(srv)


GROUP_FUNCS = {"stream": group_stream, "reduced": group_reduced, "easy": group_easy, "zhterms": group_zhterms,
               "export": group_export}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nordic UI checks for noScribe Live.")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=8800,
                        help="base port: stream +0, reduced +1, easy +2, zhterms +3")
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
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
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
