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

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_nordic.py [--only stream,reduced,easy,zhterms] [--port 8800]
        [--static DIR] [--python PY] [--work DIR]

Ports: stream uses --port, reduced --port+1, easy --port+2, zhterms --port+3. Each group starts its own
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
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  shared harness: servers, replays, DOM helpers, check reporting

FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only
DEFAULT_WORK = Path("/tmp/nslive-r9")
GROUPS = ("stream", "reduced", "easy", "zhterms")
GROUP_PORT = {"stream": 0, "reduced": 1, "easy": 2, "zhterms": 3}
THEMES = ("dark", "light")
LOCALES = ("en", "zh-TW")
TOGGLE_LABEL = {"en": "Easy view", "zh-TW": "大字模式"}
TERMS = ("說話者", "運行", "文件", "信息", "默認", "加載", "屏幕", "用戶", "設置", "搜索", "菜單", "實時")

SAMPLE_JS = """() => {
  const segs = {};
  for (const el of document.querySelectorAll('[data-segment-seq]')) {
    segs[el.getAttribute('data-segment-seq')] = el.textContent.trim();
  }
  const r = window.__nsliveReveal;
  return { segs, reveal: r ? { maxLagMs: r.maxLagMs, currentLagMs: r.currentLagMs,
                               queued: r.queued, revealedSegments: r.revealedSegments } : null };
}"""

# Installed before the app runs: rAF frame times, long tasks (>= 50 ms) and layout-shift sum.
PERF_JS = r"""
(() => {
  if (window.__nsPerf) return;
  const P = { longtasks: [], shifts: 0, frames: [] };
  window.__nsPerf = P;
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) P.longtasks.push(e.duration); })
      .observe({ type: 'longtask', buffered: true });
  } catch (e) {}
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) P.shifts += e.value; })
      .observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}
  const tick = (t) => { P.frames.push(t); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
})();
"""

PERF_READ_JS = """() => { const P = window.__nsPerf || { longtasks: [], shifts: 0, frames: [] };
  return { longtasks: P.longtasks.slice(), shifts: P.shifts, frames: P.frames.slice() }; }"""

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
def stream_body(h: Any, page: Any, path: Path, run_id: str) -> None:
    reloaded = False
    ready = ux.wait_until(lambda: ux.seg_count(page) >= 1, 8, 0.2)
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
    drained_at = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 150:
        snap = page.evaluate(SAMPLE_JS)
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
    lts = perf.get("longtasks", [])
    shifts = float(perf.get("shifts") or 0)
    print(f"INFO stream FPS (rAF frames per 1 s window, {len(windows)} windows): median {med:.0f}, p5 {p5:.0f}",
          flush=True)
    print(f"INFO stream long tasks since page load: count {len(lts)}, max {max(lts) if lts else 0:.0f} ms, "
          f"total {sum(lts):.0f} ms", flush=True)
    h.check("stream: layout-shift (CLS) sum <= 0.1", shifts <= 0.1, f"CLS {shifts:.4f}")
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
        h.scenario("easy toggle", easy_toggle_body, h, browser)
    finally:
        for _t, _l, ctx, _p in cases:
            ctx.close()
        h.stop(srv)


# ---- zhterms ----------------------------------------------------------------------------------------
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


GROUP_FUNCS = {"stream": group_stream, "reduced": group_reduced, "easy": group_easy, "zhterms": group_zhterms}


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
