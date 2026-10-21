#!/usr/bin/env python3
"""Round-7 UI checks for noScribe Live: picker switching, header fit at 360/390/430 px, zh-TW wording and
aria-labels, focus ring, toast vs run title, timeline taps, failed and stopped states, and the layout-shift
budget during a replay. Reuses the harness and DOM readers of test_ux.py and the helpers of test_i18n.py
(same directory). Servers and replays are started by this script.

    /usr/bin/python3 -I live/stress/test_r7.py [--only picker,header,zh,focus,toast,timeline,failed,cls]
        [--port 8786] [--static DIR] [--python PY] [--work DIR]

Ports 8786-8789 (--port .. --port+3) must be free. WORK defaults to /tmp/nslive-r7: src/ holds copies of the
recorded feeds and the crafted fixtures, feeds/ and logs/ and shots/ hold the rest. The feeds under
/workspace/noScribe-live/live/feeds are read only. Each group runs on its own with a fresh feeds directory on
--port; a crash in a group is one FAIL. Exit code 0 only if every check passed. Every child process is killed on exit.

Fixtures: finished = the demo feed (50 segments, run_end finished). failed = the newest *-90-corrupt.ndjson
(run_end status error). stopped = the demo cut after 20 segments with no run_end and a dead pid (status stale, shown as Stopped; crafted, run id
20261020-060000-r7-stopped). stale = the newest 03-multi-speaker feed with no run_end whose CLI pid is dead; if
there is none, the demo cut after 20 segments with pid 999999 and no run_end (crafted, run id
20261020-061500-r7-stale).

Contract checked (the UI side is being implemented, so a failure may read "contract absent"): run-loading,
run-missing (only after a definitive 404 from GET /api/runs/{id}), header-menu (theme and locale toggles below
sm), run-state-dot data-tone red|amber|green|neutral, stat-card (always 8), run-title, failed-run-notice (a
persistent toast with View / 查看), new-run-notice, the timeline hit layer (a tap maps to the nearest segment),
the transcript-scroll focus ring (inset), and the zh-TW strings and aria-labels.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent            # live/stress
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  (Harness, wait_until, DOM readers; same directory)
import test_i18n as i18n  # noqa: E402  (open_ctx, overlaps; same directory)

DEFAULT_PORT = 8786
DEFAULT_WORK = Path("/tmp/nslive-r7")
GROUPS = ("picker", "header", "zh", "focus", "toast", "timeline", "failed", "cls")
CJK = re.compile("[⺀-⿟　-〿぀-ヿ㄀-ㄯ㐀-䶿"
                 "一-鿿豈-﫿＀-￯]")
DEMO_NAME = ux.DEMO_NAME                          # 20261020-052449-demo-en-zh, 50 segments
STOPPED_ID = "20261020-060000-r7-stopped"
STALE_ID = "20261020-061500-r7-stale"
STALE_PID = 999999
ERR_TEXT = "Can't read the audio file"             # en-US humanised failure text (the raw error sits in a closed <details>)
AUDIO_DIR = "/workspace/noScribe-live/live/samples/stress"

# Visibility of the picker states, read in one evaluate per sample.
VIS_JS = r"""() => {
  const vis = (sel) => { const e = document.querySelector(sel); if (!e) return false;
    const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  return { missing: vis('[data-testid="run-missing"]'), loading: vis('[data-testid="run-loading"]'),
           title: vis('[data-testid="run-title"]') }; }"""
HEADER_JS = r"""() => {
  const vw = document.documentElement.clientWidth;
  const inside = (e) => { const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left >= -0.5 && r.right <= vw + 0.5; };
  const menu = document.querySelector('[data-testid="header-menu"]');
  const tog = Array.from(document.querySelectorAll('[data-testid="locale-toggle"],[data-testid="theme-toggle"]'));
  return { sw: document.documentElement.scrollWidth, cw: vw, menu: menu ? inside(menu) : null,
           toggles: tog.length ? tog.every(inside) : null }; }"""
RECT_JS = r"""(sel) => { const e = document.querySelector(sel); if (!e) return null;
  const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height }; }"""
TEXT_RECT_JS = r"""(sel) => { const e = document.querySelector(sel); if (!e) return null;
  const r = document.createRange(); r.selectNodeContents(e); const b = r.getBoundingClientRect();
  return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; }"""  # union of the rendered text
INNER_JS = r"""(sel) => { const e = document.querySelector(sel); return e ? e.innerText : null; }"""
TOAST_LABELS_JS = r"""() => Array.from(document.querySelectorAll('section[aria-label]'))
  .filter((s) => s.querySelector('[data-sonner-toast]') || /notif|通知/i.test(s.getAttribute('aria-label') || ''))
  .map((s) => s.getAttribute('aria-label'))"""
CMDK_JS = r"""() => { const l = document.querySelector('[cmdk-list]'); return l ? l.getAttribute('aria-label') : null; }"""
LOGO_JS = r"""() => { const e = document.querySelector('[data-testid="logo"]'); if (!e) return null;
  const parts = [e.getAttribute('aria-label'), e.getAttribute('title'), e.getAttribute('alt')];
  e.querySelectorAll('[aria-label],[title],[alt]').forEach((n) => parts.push(
    n.getAttribute('aria-label'), n.getAttribute('title'), n.getAttribute('alt')));
  return parts.filter(Boolean).join(' | '); }"""
# The orb is hidden from screen readers (aria-hidden="true", no aria-label); the failed state is read from run-state text.
ORB_JS = r"""() => { const o = document.querySelector('[data-testid="activity-orb"]');
  return o ? o.getAttribute('aria-hidden') : null; }"""
FOCUS_JS = r"""() => { const a = document.activeElement; return a ? a.getAttribute('data-testid') : null; }"""
RING_JS = r"""() => { const e = document.querySelector('[data-testid="transcript-scroll"]'); if (!e) return null;
  const cs = getComputedStyle(e);
  return { shadow: cs.boxShadow, outlineOffset: cs.outlineOffset, outlineStyle: cs.outlineStyle }; }"""
STAT_COUNT_JS = r"""() => document.querySelectorAll('[data-testid="stat-card"]').length"""
BODY_JS = r"""() => document.body.innerText"""
# Runs before the app: records every layout-shift entry (page-clock start time, value, hadRecentInput). The
# session-window CLS is computed from these in Python (session_max, copied from test_nordic.py).
CLS_JS = r"""
(() => { window.__nsShifts = [];
  try { new PerformanceObserver((list) => { for (const e of list.getEntries()) {
          window.__nsShifts.push({ t: e.startTime, v: e.value, input: e.hadRecentInput }); } })
        .observe({ type: 'layout-shift', buffered: true });
  } catch (err) { window.__nsCLSErr = String(err); }
})();
"""
SHIFTS_JS = r"""() => window.__nsShifts || []"""


# ---- fixtures ----------------------------------------------------------------------------------------
def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(raw))
        except ValueError:
            continue
    return events


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def real_stale() -> Path | None:
    """The newest 03-multi-speaker feed with no run_end whose CLI pid is dead (a killed run), if any."""
    for path in sorted(ux.FEEDS_SRC.glob("*-03-multi-speaker.ndjson"), reverse=True):
        events = read_events(path)
        if any(ev.get("type") == "run_end" for ev in events):
            continue
        start = next((ev for ev in events if ev.get("type") == "run_start"), {})
        pid = start.get("pid")
        if isinstance(pid, int) and not pid_alive(pid):
            return path
    return None


def craft(src: Path, dst: Path, rid: str, audio: str, segments: int, end_status: str | None,
          pid: int | None) -> None:
    """Writes dst: the src feed under run id rid, cut after `segments` segments, with a run_end of end_status if set."""
    out: list[dict[str, Any]] = []
    seen = 0
    for ev in read_events(src):
        kind = ev.get("type")
        if kind == "run_end":
            continue
        if kind == "segment":
            if seen >= segments:
                break
            seen += 1
        if "run_id" in ev:
            ev["run_id"] = rid
        if kind == "run_start":
            ev["audio_file"] = f"{AUDIO_DIR}/{audio}"
            if pid is not None:
                ev["pid"] = pid
        out.append(ev)
    if end_status:
        out.append({"v": 1, "type": "run_end", "t": time.time(), "seq": len(out), "run_id": rid,
                    "status": end_status, "error": None, "output_file": None, "elapsed": 20.0})
    dst.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in out) + "\n", encoding="utf-8")


def prepare(h: ux.Harness) -> None:
    """Copies the recorded feeds into the scratch dir (originals are read only)."""
    h.demo_src = h.src / DEMO_NAME
    shutil.copyfile(ux.FEEDS_SRC / DEMO_NAME, h.demo_src)
    corrupt = sorted(ux.FEEDS_SRC.glob("*-90-corrupt.ndjson"))
    if not corrupt:
        raise RuntimeError(f"no *-90-corrupt.ndjson in {ux.FEEDS_SRC}")
    h.failed_src = h.src / corrupt[-1].name
    shutil.copyfile(corrupt[-1], h.failed_src)
    stale = real_stale()
    h.stale_src = None
    if stale is not None:
        h.stale_src = h.src / stale.name
        shutil.copyfile(stale, h.stale_src)
    print(f"sources: demo {DEMO_NAME}, failed {h.failed_src.name}, "
          f"stale {h.stale_src.name if h.stale_src else 'crafted (pid %d)' % STALE_PID}", flush=True)


def fixtures(h: ux.Harness, feeds: Path, parts: tuple[str, ...]) -> dict[str, str]:
    """Copies the named fixture feeds into feeds; returns name -> run id."""
    ids: dict[str, str] = {}
    if "demo" in parts:
        shutil.copyfile(h.demo_src, feeds / DEMO_NAME)
        ids["demo"] = ux.feed_info(h.demo_src)["run_id"]
    if "failed" in parts:
        shutil.copyfile(h.failed_src, feeds / h.failed_src.name)
        ids["failed"] = ux.feed_info(h.failed_src)["run_id"]
    if "stopped" in parts:
        craft(h.demo_src, feeds / f"{STOPPED_ID}.ndjson", STOPPED_ID, "r7-stopped.mp3", 20, None, STALE_PID)
        ids["stopped"] = STOPPED_ID
    if "stale" in parts:
        if h.stale_src is not None:
            shutil.copyfile(h.stale_src, feeds / h.stale_src.name)
            ids["stale"] = ux.feed_info(h.stale_src)["run_id"]
        else:
            craft(h.demo_src, feeds / f"{STALE_ID}.ndjson", STALE_ID, "r7-stale.mp3", 20, None, STALE_PID)
            ids["stale"] = STALE_ID
    return ids


# ---- helpers -----------------------------------------------------------------------------------------
def slug(run_id: str) -> str:
    """The run id without its timestamp prefix, e.g. demo-en-zh or 90-corrupt."""
    parts = run_id.split("-", 2)
    return parts[2] if len(parts) == 3 else run_id


def sample_states(page: Any, seconds: float, step: float = 0.1) -> list[dict[str, bool]]:
    out: list[dict[str, bool]] = []
    end = time.monotonic() + seconds
    while True:
        try:
            out.append(page.evaluate(VIS_JS))
        except Exception:  # navigation or a half-built page: count it as neither loading nor titled
            out.append({"missing": False, "loading": False, "title": False})
        if time.monotonic() >= end:
            return out
        time.sleep(step)


def absent_note(page: Any, selectors: list[str]) -> str:
    """'; contract absent: ...' listing the hooks that are not in the DOM at all (empty if all are present)."""
    gone = [sel.split('"')[1] for sel in selectors if page.locator(sel).count() == 0]
    return f"; contract absent: {', '.join(gone)}" if gone else ""


def pick_run(page: Any, rid: str) -> bool:
    """Opens the picker and clicks the option for rid. Returns False if the option did not appear."""
    page.locator('[data-testid="run-picker"]').first.click(timeout=5000)
    option = page.locator(f'[data-testid="run-option"][data-run-id="{rid}"]')
    if option.count() == 0:
        option = page.locator(f'[data-run-id="{rid}"]')
    if not ux.wait_until(lambda: option.count() > 0 and option.first.is_visible(), 5, 0.2):
        return False
    option.first.click(timeout=5000)
    return True


def switch_locale(page: Any) -> bool:
    """Clicks the locale toggle, opening header-menu first when the toggle is not on screen."""
    toggle = page.locator('[data-testid="locale-toggle"]')
    if toggle.count() == 0 or not toggle.first.is_visible():
        menu = page.locator('[data-testid="header-menu"]')
        if menu.count() == 0:
            return False
        menu.first.click(timeout=5000)
        toggle = page.locator('[data-testid="locale-toggle"]')
    if toggle.count() == 0:
        return False
    toggle.first.click(timeout=5000)
    return True


def visible_rect(rect: dict[str, float] | None) -> bool:
    return bool(rect) and rect["w"] > 0 and rect["h"] > 0


def wait_segments(page: Any, n: int, timeout: float = 60) -> int:
    return ux.wait_until(lambda: ux.seg_count(page) >= n, timeout, 0.3) or 0


def open_run(page: Any, h: ux.Harness, port: int, rid: str) -> None:
    page.goto(f"{h.url(port)}?run={rid}", wait_until="domcontentloaded", timeout=30000)
    ux.wait_until(lambda: page.locator('[data-testid="run-state-dot"]').count() > 0, 20, 0.3)


def tone_of(page: Any) -> str | None:
    return page.evaluate(ux.ATTR_JS, ['[data-testid="run-state-dot"]', "data-tone"])


# Session-window CLS (the definition Chrome and web-vitals use): non-input shifts grouped into windows that end
# after a 1 s gap or after 5 s; the score is the largest window sum. Copied from test_nordic.py (cls_report).
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


# ---- groups ------------------------------------------------------------------------------------------
def group_picker(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("picker")
    ids = fixtures(h, feeds, ("demo", "failed", "stopped"))
    h.serve(port, feeds, "picker")
    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: page.locator('[data-testid="run-picker"]').count() > 0, 20, 0.3)
        for name in ("demo", "failed", "stopped"):
            rid = ids[name]
            picked = pick_run(page, rid)
            samples = sample_states(page, 6.0)
            missing = sum(1 for s in samples if s["missing"])
            uncovered = sum(1 for s in samples if not (s["loading"] or s["title"]))
            note = absent_note(page, ['[data-testid="run-title"]', '[data-testid="run-loading"]',
                                      '[data-testid="run-missing"]'])
            h.check(f"picker {name}: run-missing never visible and loading-or-title at every 100 ms sample (6 s)",
                    picked and missing == 0 and uncovered == 0,
                    f"picked {picked}, {len(samples)} samples, run-missing {missing}, "
                    f"neither loading nor title {uncovered}{note}")
            title = page.evaluate(ux.TEXT_JS, '[data-testid="run-title"]') or ""
            h.check(f"picker {name}: ends on run-title naming the file", slug(rid) in title,
                    f"title {title!r}, want it to contain {slug(rid)!r}{note}")
        h.shot(page, "r7-picker.png")
    finally:
        ctx.close()

    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
        samples = sample_states(page, 6.0)
        missing = sum(1 for s in samples if s["missing"])
        h.check("cold ?run=<existing>: run-missing never visible in 6 s", missing == 0,
                f"{missing} of {len(samples)} samples showed run-missing")
    finally:
        ctx.close()

    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(f"{h.url(port)}?run=does-not-exist", wait_until="domcontentloaded", timeout=30000)
        shown = ux.wait_until(lambda: page.evaluate(VIS_JS)["missing"], 8, 0.2)
        h.check("?run=does-not-exist: run-missing visible within 8 s", bool(shown),
                "run-missing shown" if shown else "run-missing not shown within 8 s")
    finally:
        ctx.close()


def group_header(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("header")
    ids = fixtures(h, feeds, ("demo",))
    h.serve(port, feeds, "header")
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, 0.6, 2, "header-live")       # still running while the widths are checked
    _, live_id = h.new_run(feeds, before, "header-live")
    for kind, rid in (("finished", ids["demo"]), ("live", live_id)):
        for locale in ("en-US", "zh-TW"):
            for width in (360, 390, 430):
                ctx, page = i18n.open_ctx(browser, locale, viewport={"width": width, "height": 800})
                try:
                    page.goto(f"{h.url(port)}?run={rid}", wait_until="domcontentloaded", timeout=30000)
                    ux.wait_until(lambda: page.locator('[data-testid="run-title"]').count() > 0, 20, 0.3)
                    info = page.evaluate(HEADER_JS)
                    h.check(f"header {kind} {locale} {width}px: no horizontal overflow",
                            info["sw"] <= info["cw"], f"scrollWidth {info['sw']}, clientWidth {info['cw']}")
                    menu_ok = info["menu"] is True or info["toggles"] is True
                    h.check(f"header {kind} {locale} {width}px: header-menu (or toggles) within the viewport",
                            menu_ok, f"header-menu {info['menu']}, toggles {info['toggles']}")
                finally:
                    ctx.close()


def group_zh(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("zh")
    ids = fixtures(h, feeds, ("demo",))
    h.serve(port, feeds, "zh")
    ctx, page = i18n.open_ctx(browser, "zh-TW")
    try:
        page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
        wait_segments(page, 5)
        before = h.feeds_now(feeds)                                   # a new run gives a toast in zh
        h.start_replay(h.demo_src, feeds, 1.5, 2, "zh-toast")
        h.new_run(feeds, before, "zh-toast")
        ux.wait_until(lambda: page.locator('[data-testid="new-run-notice"]').count() > 0, 15, 0.2)
        for sel, name in (('[data-testid="stage-card"]', "stage card"),
                          ('[data-testid="timeline-card"]', "timeline card")):
            text = page.evaluate(INNER_JS, sel)
            if text is None:
                h.check(f"zh-TW: {name} innerText has no 'of'", False, "contract absent")
                continue
            hit = re.search(r"\bof\b", text, re.I)
            detail = "clean" if not hit else f"found {text[max(0, hit.start() - 30):hit.end() + 30]!r}"
            h.check(f"zh-TW: {name} innerText has no 'of'", hit is None, detail)
        labels = page.evaluate(TOAST_LABELS_JS) or []
        h.check("zh-TW: toast region aria-label (section[aria-label]) contains CJK",
                bool(labels) and all(CJK.search(lbl or "") for lbl in labels), f"labels {labels}")
        page.locator('[data-testid="run-picker"]').first.click(timeout=5000)
        ux.wait_until(lambda: page.locator("[cmdk-list]").count() > 0, 5, 0.2)
        cmdk = page.evaluate(CMDK_JS)
        h.check("zh-TW: picker list [cmdk-list] aria-label contains CJK",
                bool(cmdk) and bool(CJK.search(cmdk)), f"aria-label {cmdk!r}")
        page.keyboard.press("Escape")
        logo = page.evaluate(LOGO_JS)
        h.check("zh-TW: logo aria-label contains CJK", bool(logo) and bool(CJK.search(logo)), f"logo {logo!r}")
        body = page.evaluate(BODY_JS) or ""
        h.check("zh-TW: no 說話者 anywhere in document.body.innerText", "說話者" not in body,
                "absent" if "說話者" not in body else "present")
        h.shot(page, "r7-zh.png")
    finally:
        ctx.close()

    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
        wait_segments(page, 5)
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 1.5, 2, "zh-en-toast")
        h.new_run(feeds, before, "zh-en-toast")
        shown = ux.wait_until(lambda: page.locator('[data-testid="new-run-notice"]').is_visible(), 15, 0.2)
        switched = switch_locale(page)
        time.sleep(1.0)
        notice = page.locator('[data-testid="new-run-notice"]')
        vis = notice.count() > 0 and notice.first.is_visible()
        text = notice.first.inner_text() if vis else ""
        ok = bool(shown) and switched and (not vis or bool(CJK.search(text)))
        h.check("toast created in en (new-run-notice) is gone or zh after switching to zh-TW", ok,
                f"shown {bool(shown)}, switched {switched}, visible after {vis}, text {text[:60]!r}")
    finally:
        ctx.close()


def group_focus(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("focus")
    ids = fixtures(h, feeds, ("demo",))
    h.serve(port, feeds, "focus")
    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
        wait_segments(page, 5)
        reached = False
        for _ in range(80):
            page.keyboard.press("Tab")
            if page.evaluate(FOCUS_JS) == "transcript-scroll":
                reached = True
                break
        ring = page.evaluate(RING_JS) if reached else None
        if ring is None:
            h.check("focus: transcript-scroll focus ring is inset after Tab", False,
                    "transcript-scroll not reached by Tab" if not reached else "contract absent")
            return
        offset = ring.get("outlineOffset") or "0px"
        try:
            offset_px = float(offset.replace("px", ""))
        except ValueError:
            offset_px = 0.0
        inset = "inset" in (ring.get("shadow") or "") or offset_px < 0
        h.check("focus: transcript-scroll focus ring is inset after Tab", inset,
                f"box-shadow {ring.get('shadow')!r}, outline-offset {offset!r}, outline-style {ring.get('outlineStyle')!r}")
    finally:
        ctx.close()


def group_toast(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("toast")
    ids = fixtures(h, feeds, ("demo",))
    h.serve(port, feeds, "toast")
    for width in (1440, 390):
        ctx, page = i18n.open_ctx(browser, "en-US", viewport={"width": width, "height": 900})
        try:
            page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
            wait_segments(page, 5)
            before = h.feeds_now(feeds)
            h.start_replay(h.demo_src, feeds, 1.5, 2, f"toast-{width}")
            h.new_run(feeds, before, f"toast-{width}")
            shown = ux.wait_until(lambda: page.locator('[data-testid="new-run-notice"]').is_visible(), 15, 0.2)
            rect_n = page.evaluate(RECT_JS, '[data-testid="new-run-notice"]')
            rect_t = page.evaluate(RECT_JS, '[data-testid="run-title"]')          # h2 element box (block, full card width)
            text_t = page.evaluate(TEXT_RECT_JS, '[data-testid="run-title"]')    # union of the h2's rendered text
            ok = (bool(shown) and visible_rect(rect_n) and visible_rect(rect_t) and visible_rect(text_t)
                  and not i18n.overlaps(rect_n, text_t))
            h.check(f"toast vs run-title at {width}px: new-run-notice does not intersect run-title", ok,
                    f"shown {bool(shown)}, notice {rect_n}, title element {rect_t}, title text {text_t}")
            h.shot(page, f"r7-toast-{width}.png")
        finally:
            ctx.close()


def group_timeline(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("timeline")
    ids = fixtures(h, feeds, ("demo",))
    h.serve(port, feeds, "timeline")
    ctx, page = i18n.open_ctx(browser, "en-US", viewport={"width": 390, "height": 844})
    try:
        page.goto(f"{h.url(port)}?run={ids['demo']}", wait_until="domcontentloaded", timeout=30000)
        wait_segments(page, 50, 60)
        for idx in (0, 1, 25, 49):
            loc = page.locator(f'[data-timeline-index="{idx}"]').first
            if loc.count() == 0:
                h.check(f"timeline at 390px: tap maps to segment {idx}", False, "contract absent")
                continue
            loc.scroll_into_view_if_needed(timeout=5000)
            box = loc.bounding_box()
            if not box:
                h.check(f"timeline at 390px: tap maps to segment {idx}", False, "no bounding box")
                continue
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            active = ux.wait_until(
                lambda: page.locator(f'[data-segment-index="{idx}"][data-active="true"]').count() > 0, 3, 0.2)
            h.check(f"timeline at 390px: tap at the centre of [data-timeline-index={idx}] activates segment {idx}",
                    bool(active), f"box {box}")
    finally:
        ctx.close()


def group_failed(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("failed")
    ids = fixtures(h, feeds, ("demo", "failed", "stopped", "stale"))
    h.serve(port, feeds, "failed")
    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        open_run(page, h, port, ids["failed"])
        orb = page.evaluate(ORB_JS)
        state = page.evaluate(INNER_JS, '[data-testid="run-state"]') or ""
        h.check('failed run: activity orb aria-hidden="true", and run-state text says Failed (or 失敗)',
                orb == "true" and bool(re.search(r"Failed|失敗", state, re.I)),
                f"orb aria-hidden {orb!r}, run-state innerText {state!r}")
        h.check("failed run: run-state-dot data-tone red", tone_of(page) == "red", f"data-tone {tone_of(page)!r}")
        body = page.evaluate(BODY_JS) or ""
        n_err = body.count(ERR_TEXT)
        h.check("failed run: the humanised error text appears once in document.body.innerText", n_err == 1,
                f"{n_err} occurrence(s)")
        stage = page.evaluate(ux.TEXT_JS, '[data-testid="stage-card"]') or ""
        n_failed = len(re.findall(r"\bFailed\b", stage))
        h.check("failed run: 'Failed' words in the stage card <= 1", bool(stage) and n_failed <= 1,
                f"{n_failed} in the stage card")
        h.shot(page, "r7-failed.png")
        open_run(page, h, port, ids["stopped"])
        h.check("stopped run (no run_end, dead pid = stale): run-state-dot data-tone amber", tone_of(page) == "amber", f"data-tone {tone_of(page)!r}")
        if "stale" in ids:
            open_run(page, h, port, ids["stale"])
            h.check("stale run (dead CLI pid): run-state-dot data-tone amber", tone_of(page) == "amber",
                    f"data-tone {tone_of(page)!r}")
    finally:
        ctx.close()

    ctx, page = i18n.open_ctx(browser, "en-US")
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: page.locator('[data-testid="run-state-dot"]').count() > 0, 20, 0.3)
        before = h.feeds_now(feeds)
        h.start_replay(h.failed_src, feeds, 1, 5, "failed-follow")    # the failed feed replayed while following
        h.new_run(feeds, before, "failed-follow")
        notice = page.locator('[data-testid="failed-run-notice"]')
        shown = ux.wait_until(lambda: notice.is_visible(), 20, 0.2)
        h.check("follow: failed-run-notice shows when a followed run fails", bool(shown),
                "shown" if shown else "not shown within 20 s")
        time.sleep(10)
        still = notice.count() > 0 and notice.first.is_visible()
        h.check("follow: failed-run-notice still visible 10 s later", bool(shown) and still, f"visible {still}")
        view = notice.locator("button, a").filter(has_text=re.compile("View|查看"))
        if view.count() == 0:
            h.check("follow: failed-run-notice View action sets ?run=", False, "contract absent")
        else:
            view.first.click(timeout=5000)
            moved = ux.wait_until(lambda: "run=" in page.url, 5, 0.2)
            h.check("follow: failed-run-notice View action sets ?run=", bool(moved), f"url {page.url}")
    finally:
        ctx.close()


def group_cls(h: ux.Harness, browser: Any, port: int) -> None:
    feeds = h.new_feeds("cls")
    h.serve(port, feeds, "cls")
    ctx, page = i18n.open_ctx(browser, "en-US", extra=CLS_JS)
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 2, 2, "cls")
        path, _ = h.new_run(feeds, before, "cls")
        ux.wait_until(lambda: page.evaluate(STAT_COUNT_JS) > 0, 3, 0.2)     # short cap: the replay must not end first
        counts: list[int] = []
        end = time.monotonic() + 240
        while time.monotonic() < end:
            try:
                counts.append(page.evaluate(STAT_COUNT_JS))
            except Exception:
                counts.append(-1)
            if ux.feed_info(path)["ended"]:
                break
            time.sleep(0.25)
        shifts = page.evaluate(SHIFTS_JS) or []
        raw = [s for s in shifts if not s.get("input")]
        cls_max = session_max([(float(s["t"]), float(s["v"])) for s in raw])
        raw_sum = sum(float(s["v"]) for s in raw)
        bad = [c for c in counts if c != 8]
        note = absent_note(page, ['[data-testid="stat-card"]'])
        h.check("cls: stat-card count is 8 at every 250 ms sample of a speed-2 replay",
                bool(counts) and not bad,
                f"{len(counts)} samples, values {sorted(set(counts))}{note}")
        print(f"INFO cls: session-window max {cls_max:.4f}, raw sum {raw_sum:.4f} over {len(raw)} non-input "
              f"shifts ({len(shifts) - len(raw)} input-caused excluded)", flush=True)
        h.check("cls: layout-shift CLS (session-window max, Chrome definition) <= 0.1", cls_max <= 0.1,
                f"session-window max {cls_max:.4f}, raw sum {raw_sum:.4f} over {len(raw)} non-input shifts")
        h.shot(page, "r7-cls.png")
    finally:
        ctx.close()


GROUP_FUNCS: dict[str, Callable[[ux.Harness, Any, int], None]] = {
    "picker": group_picker, "header": group_header, "zh": group_zh, "focus": group_focus,
    "toast": group_toast, "timeline": group_timeline, "failed": group_failed, "cls": group_cls,
}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Round-7 UI checks for noScribe Live (en-US and zh-TW).")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="server port for each group (ports --port .. --port+3 must be free; default: %(default)s)")
    parser.add_argument("--static", default=str(ux.DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=ux.DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, ux._exit_on_term)
    args = parse_args(argv)
    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUP_FUNCS]
    if unknown:
        print(f"unknown group(s) {unknown}; choose from {','.join(GROUPS)}", file=sys.stderr)
        return 2
    busy = [p for p in range(args.port, args.port + 4) if ux.port_busy(p)]
    if busy:
        print(f"FAIL setup: port(s) {busy} already in use; not touching those processes", flush=True)
        return 2
    h = ux.Harness(args)
    try:
        prepare(h)
    except Exception as exc:
        print(f"FAIL setup: fixtures: {exc!r}", flush=True)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"FAIL setup: playwright is not importable with this python: {exc}", flush=True)
        return 2
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for group in groups:
                print(f"== group {group}", flush=True)
                try:
                    GROUP_FUNCS[group](h, browser, args.port)
                except Exception as exc:
                    text = str(exc).splitlines()[0][:200] if str(exc) else ""
                    h.check(f"{group}: group completed", False, f"crashed: {type(exc).__name__}: {text}")
                finally:
                    h.reap()
        finally:
            browser.close()
    h.cleanup()
    return 0 if h.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
