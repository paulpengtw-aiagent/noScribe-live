#!/usr/bin/env python3
"""i18n and UI-contract checks for noScribe Live: en and zh-TW strings, html lang, the locale toggle and
its persistence, the freeze while reconnecting (SIGSTOP), the outage that spans a finished run (SIGKILL,
replay finishes, restart), banner layout shift, toast overlap, focus ring, mobile 390x844 checks, and a
static scan for CJK characters in string literals of the en-capable component code.

Reuses the harness of test_ux.py (same directory: servers, replays, DOM readers). Run from any directory
with the system Python that has Playwright:

    /usr/bin/python3 -I live/stress/test_i18n.py [--only static,ui,freeze,outage] [--port 8780]
        [--static DIR] [--python PY] [--work DIR]

--port hosts the main server (finished run: en-US and zh-TW contexts, focus, mobile, toast); --port+1 the
freeze server (SIGSTOP, heartbeat 4 s), --port+2 the outage server (SIGKILL, then restart). WORK defaults to
/tmp/nslive-r6. The demo feed is copied from /workspace/noScribe-live/live/feeds (read only). Each group runs
on its own; a crash is one FAIL. Exit code 0 only if every check passed. Every child process is killed on exit.

Contract checked (the UI side is being implemented): localStorage noscribe-live-locale = en | zh-TW, default
from the first browser language; html lang en | zh-Hant-TW; [data-testid=locale-toggle]; conn-state
connecting -> live -> reconnecting -> live; stage-card data-frozen; last-update; conn-banner overlay that
does not move transcript-scroll; new-run-notice that does not overlap the timeline card; a visible focus ring
on transcript-scroll; mobile first paragraph top <= 400 px and timeline hit areas >= 24 px.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # live/stress
sys.path.insert(0, str(HERE))                   # `python -I` does not put the script directory on sys.path
import test_ux as ux  # noqa: E402  (Harness, wait_until, DOM readers; same directory)

LIVE_DIR = ux.LIVE_DIR                          # live/
REPO_ROOT = LIVE_DIR.parent
DEFAULT_PORT = 8780
DEFAULT_WORK = Path("/tmp/nslive-r6")
GROUPS = ("static", "ui", "freeze", "outage")
LOCALE_KEY = "noscribe-live-locale"
LANG_FOR = {"en": "en", "zh-TW": "zh-Hant-TW"}  # expected <html lang> per locale
OTHER = {"en": "zh-TW", "zh-TW": "en"}
MOBILE = {"width": 390, "height": 844}
CJK = re.compile(r"[⺀-⿟　-〿぀-ヿ㄀-ㄯ㐀-䶿一-鿿"
                 r"豈-﫿＀-￯]")
STRING_RE = re.compile("|".join([r'"(?:[^"\\\n]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'", r"`(?:[^`\\]|\\.)*`"]))
STATIC_DIRS = ("web/src/components", "web/src/lib")   # relative to live/; src/i18n and lib/zh-tw.ts are exempt
LAST_RE = re.compile(r"(?:Last update|最後更新)\s*(\d{2}:\d{2}:\d{2})")
ELAPSED_RE = re.compile(r"Elapsed\D{0,30}?(\d+(?::\d+)+)")

LANG_JS = "() => document.documentElement.getAttribute('lang')"
STORED_JS = "(key) => { try { return localStorage.getItem(key); } catch (e) { return 'ERR'; } }"
CARD_TOP_JS = """() => { const e = document.querySelector('[data-testid="transcript-scroll"]');
  return e ? e.getBoundingClientRect().top : null; }"""
STAGE_TEXT_JS = """() => { const e = document.querySelector('[data-testid="stage-card"]');
  return e ? e.innerText : ''; }"""
FIRST_PARA_JS = """() => { const p = document.querySelector('[data-testid="paragraph"]');
  return p ? p.getBoundingClientRect().top : null; }"""
ACTIVE_SCROLL_JS = """() => { const a = document.activeElement;
  return !!a && a.getAttribute('data-testid') === 'transcript-scroll'; }"""
FOCUS_JS = """() => { const e = document.querySelector('[data-testid="transcript-scroll"]');
  if (!e) return null; const cs = getComputedStyle(e);
  return { outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth, boxShadow: cs.boxShadow,
           focusVisible: e.matches(':focus-visible') }; }"""
RECT_JS = """(sels) => { for (const s of sels) { const e = document.querySelector(s);
  if (e) { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; } }
  return null; }"""
# Non-empty text of the picker trigger. The trigger is lazy-loaded, so locale_body polls this before reading CHROME_JS.
PICKER_TEXT_JS = """() => ((document.querySelector('[data-testid="run-picker"]') || {}).textContent || '').trim()"""
# Text of header, stage card, timeline card, banner and picker trigger, without transcript paragraphs and turns,
# and without the locale toggle (its endonym label 中 is by design).
CHROME_JS = """() => {
  const pick = (el) => { if (!el) return null; const c = el.cloneNode(true);
    c.querySelectorAll('[data-testid="paragraph"],[data-testid="turn"],[data-testid="locale-toggle"]').forEach((n) => n.remove());
    return c.textContent.replace(/\\s+/g, ' ').trim(); };
  const block = document.querySelector('[data-timeline-index]');
  const tl = document.querySelector('[data-testid="timeline-card"]') ||
    (block ? block.closest('section,aside') : null);
  return { header: pick(document.querySelector('header')), stage: pick(document.querySelector('[data-testid="stage-card"]')),
           timeline: pick(tl), banner: pick(document.querySelector('[data-testid="conn-banner"]')),
           picker: pick(document.querySelector('[data-testid="run-picker"]')) }; }"""
# Per timeline block: the hit layer is the ::before pseudo-element. Pass when max(own width, ::before width) >= 24 px.
HIT_JS = """() => Array.from(document.querySelectorAll('[data-timeline-index]')).map((el) => {
  const visual = el.getBoundingClientRect().width;
  const before = parseFloat(getComputedStyle(el, '::before').width) || 0;
  const hit = Math.max(visual, before);
  return { index: el.getAttribute('data-timeline-index'), visual: Math.round(visual * 10) / 10,
           before: Math.round(before * 10) / 10, hit: Math.round(hit * 10) / 10, ok: hit >= 24 }; })"""


def open_ctx(browser: Any, locale: str, viewport: dict[str, int] | None = None,
             extra: str | None = None) -> tuple[Any, Any]:
    """New context with the browser locale (Playwright locale = the first browser language)."""
    ctx = browser.new_context(viewport=viewport or ux.VIEWPORT, locale=locale)
    ctx.add_init_script(ux.INIT_JS)
    if extra:
        ctx.add_init_script(extra)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    return ctx, page


def overlaps(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"])


def elapsed(page: Any) -> str | None:
    match = ELAPSED_RE.search(page.evaluate(STAGE_TEXT_JS) or "")
    return match.group(1) if match else None


def static_cjk_scan(live_dir: Path) -> list[str]:
    """file:line for every CJK character inside a string literal of the component and lib code."""
    offenders: list[str] = []
    for sub in STATIC_DIRS:
        for path in sorted((live_dir / sub).rglob("*")):
            if path.suffix not in (".ts", ".tsx"):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/i18n/" in f"/{rel}" or rel.endswith("lib/zh-tw.ts"):
                continue
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("//", "/*", "*")):
                    continue
                if any(CJK.search(m.group(0)) for m in STRING_RE.finditer(line)):
                    offenders.append(f"{rel}:{num}: {stripped[:140]}")
    return offenders


def finished_run(h: ux.Harness, port: int, feeds: Path, speed: float, max_gap: float, tag: str) -> tuple[Any, str, int]:
    """Serves feeds on port, replays the demo to its end; returns (feed path, run id, segment count)."""
    before = h.feeds_now(feeds)
    h.start_replay(h.demo_src, feeds, speed, max_gap, tag)
    path, run_id = h.new_run(feeds, before, tag)
    if not ux.wait_until(lambda: ux.feed_info(path)["ended"], 240, 1.0):
        raise RuntimeError(f"{tag}: replay did not reach run_end within 240 s")
    return path, run_id, ux.feed_info(path)["segments"]


# ---- ui: en-US and zh-TW contexts, focus ring, mobile, toast --------------------------------------
def locale_body(h: ux.Harness, browser: Any, port: int, locale: str, expected: int) -> None:
    ctx, page = open_ctx(browser, locale)
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= expected, 60, 0.3)
        want = "en" if locale == "en-US" else "zh-TW"
        lang = page.evaluate(LANG_JS)
        h.check(f"i18n {want}: html lang is {LANG_FOR[want]} for browser locale {locale}",
                lang == LANG_FOR[want], f"lang {lang!r}")
        if want == "en":
            # The picker trigger is lazy-loaded: wait up to 5 s for it to carry text before reading the chrome.
            ux.wait_until(lambda: bool(page.evaluate(PICKER_TEXT_JS)), 5, 0.2)
        chrome = page.evaluate(CHROME_JS) or {}
        if want == "en":
            picker = chrome.get("picker") or ""
            stage = chrome.get("stage") or ""
            h.check("i18n en: picker trigger reads 'Follow newest run' and stats show 'Elapsed'",
                    "Follow newest run" in picker and "Elapsed" in stage,
                    f"picker {picker[:60]!r}, stage has Elapsed {'Elapsed' in stage}")
            joined = " | ".join(f"{k}={v}" for k, v in chrome.items() if v)
            cjk = CJK.findall(joined)
            h.check("i18n en: no CJK in header, stage card, timeline card or banner text (transcript excluded)",
                    not cjk, f"CJK {''.join(cjk)[:40]!r}" if cjk else "none")
        else:
            cjk_text = " ".join(str(chrome.get(k) or "") for k in ("header", "stage", "picker"))
            h.check("i18n zh-TW: header, stage card and picker show CJK text", bool(CJK.search(cjk_text)),
                    f"header+stage+picker {cjk_text[:60]!r}")
        h.shot(page, f"i18n-{want}.png")

        other = OTHER[want]
        toggle = page.locator('[data-testid="locale-toggle"]')
        if toggle.count() == 0:
            h.check(f"i18n toggle {want} -> {other}: [data-testid=locale-toggle] present", False, "contract absent")
            return
        toggle.first.click(timeout=5000)
        switched = ux.wait_until(lambda: page.evaluate(LANG_JS) == LANG_FOR[other], 5, 0.2)
        stored = page.evaluate(STORED_JS, LOCALE_KEY)
        h.check(f"i18n toggle {want} -> {other}: html lang and localStorage follow",
                bool(switched) and stored == other, f"lang {page.evaluate(LANG_JS)!r}, stored {stored!r}")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= expected, 60, 0.3)
        lang2 = page.evaluate(LANG_JS)
        stored2 = page.evaluate(STORED_JS, LOCALE_KEY)
        h.check(f"i18n persist: {other} survives reload", lang2 == LANG_FOR[other] and stored2 == other,
                f"lang {lang2!r}, stored {stored2!r}")
    finally:
        ctx.close()


def focus_body(h: ux.Harness, browser: Any, port: int, expected: int) -> None:
    ctx, page = open_ctx(browser, "en-US")
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= expected, 60, 0.3)
        focused = False
        for _ in range(80):
            page.keyboard.press("Tab")
            if page.evaluate(ACTIVE_SCROLL_JS):
                focused = True
                break
        style = page.evaluate(FOCUS_JS) or {}
        shadow = style.get("boxShadow") or "none"
        literal = shadow != "none" or style.get("outlineStyle", "none") != "none"
        # Stricter: a box-shadow colour with alpha >= 0.25 or a drawn outline (a 0.08-alpha ring is invisible).
        alphas = [float(c.split(",")[3]) if c.count(",") == 3 else 1.0
                  for c in re.findall(r"rgba?\(([^)]*)\)", shadow)]
        outline_px = float((style.get("outlineWidth") or "0px").replace("px", "") or 0)
        visible = any(a >= 0.25 for a in alphas) or (style.get("outlineStyle", "none") != "none" and outline_px > 0)
        h.check("focus: transcript-scroll reached by Tab shows a visible ring (box-shadow alpha >= 0.25 or outline)",
                focused and visible, f"focused {focused}, literal rule {literal}, visible {visible}, {style}")
        h.shot(page, "focus-transcript.png")
    finally:
        ctx.close()


def mobile_body(h: ux.Harness, browser: Any, port: int, expected: int) -> None:
    ctx, page = open_ctx(browser, "en-US", viewport=MOBILE)
    try:
        page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= expected, 60, 0.3)
        top = page.evaluate(FIRST_PARA_JS)
        h.check("mobile 390x844: first paragraph top <= 400 px on a finished run",
                top is not None and top <= 400, f"top {top}")
        blocks = page.evaluate(HIT_JS) or []
        bad = [b for b in blocks if not b["ok"]]
        visuals = [b["visual"] for b in blocks]
        hits = [b["hit"] for b in blocks]
        h.check("mobile 390x844: every timeline block has a >= 24 px hit area (max of own width and ::before width)",
                bool(blocks) and not bad,
                f"{len(blocks)} blocks, {len(bad)} below 24 px {bad[:3]}; visual width min {min(visuals, default=None)} px, "
                f"hit min {min(hits, default=None)} px")
        h.shot(page, "i18n-mobile-390.png")
    finally:
        ctx.close()


def toast_body(h: ux.Harness, browser: Any, port: int, feeds: Path, run_id: str, expected: int) -> None:
    ctx, page = open_ctx(browser, "en-US")
    try:
        page.goto(f"{h.url(port)}?run={run_id}", wait_until="domcontentloaded", timeout=30000)
        ux.wait_until(lambda: ux.seg_count(page) >= expected, 60, 0.3)
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 1.5, 2, "toast")
        h.new_run(feeds, before, "toast")
        notice = ux.wait_until(lambda: page.locator('[data-testid="new-run-notice"]').is_visible(), 15, 0.2)
        rect_n = page.evaluate(RECT_JS, ['[data-testid="new-run-notice"]'])
        rect_t = page.evaluate(RECT_JS, ['[data-testid="timeline-card"]', '[data-testid="timeline"]'])
        clear = bool(rect_n and rect_t) and not overlaps(rect_n, rect_t)
        h.check("toast: new-run-notice does not overlap the timeline card's bounding box",
                bool(notice) and clear, f"visible {bool(notice)}, notice {rect_n}, timeline {rect_t}")
        h.shot(page, "i18n-toast.png")
    finally:
        ctx.close()


def group_ui(h: ux.Harness, browser: Any) -> None:
    feeds = h.new_feeds("i18n-ui")
    srv = h.serve(h.port, feeds, "ui")
    try:
        _path, run_id, expected = finished_run(h, h.port, feeds, 8, 2, "ui")
        h.scenario("ui locale en-US", locale_body, h, browser, h.port, "en-US", expected)
        h.scenario("ui locale zh-TW", locale_body, h, browser, h.port, "zh-TW", expected)
        h.scenario("ui focus ring", focus_body, h, browser, h.port, expected)
        h.scenario("ui mobile 390x844", mobile_body, h, browser, h.port, expected)
        h.scenario("ui toast overlap", toast_body, h, browser, h.port, feeds, run_id, expected)
    finally:
        ux.Harness.stop(srv)


# ---- freeze: SIGSTOP the server mid-run ----------------------------------------------------------
def group_freeze(h: ux.Harness, browser: Any) -> None:
    feeds = h.new_feeds("i18n-freeze")
    port = h.port + 1
    srv = h.serve(port, feeds, "freeze")
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 0.5, 2, "freeze")
        h.new_run(feeds, before, "freeze")
        ctx, page = open_ctx(browser, "en-US", extra="window.__NSLIVE_HEARTBEAT_TIMEOUT_MS = 4000;")
        try:
            page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
            ux.wait_until(lambda: ux.seg_count(page) >= 2, 60, 0.3)
            live_top = page.evaluate(CARD_TOP_JS)
            os.kill(srv.pid, signal.SIGSTOP)
            t0 = time.monotonic()
            state = ux.wait_until(lambda: ux.conn_state(page) == "reconnecting", 10, 0.2)
            took = time.monotonic() - t0
            frozen = ux.wait_until(lambda: ux.attr_of(page, '[data-testid="stage-card"]', "data-frozen") == "true", 3, 0.2)
            h.check("freeze: data-state reconnecting within 10 s of SIGSTOP (4 s heartbeat)",
                    bool(state), f"conn-state {ux.conn_state(page)!r} after {took:.1f} s")
            frozen_attr = ux.attr_of(page, '[data-testid="stage-card"]', "data-frozen")
            h.check("freeze: stage card data-frozen=true while not live", bool(frozen),
                    f"data-frozen {frozen_attr!r}")
            last = page.locator('[data-testid="last-update"]')
            last_text = (last.first.inner_text(timeout=3000) if last.count() else "") or ""
            match = LAST_RE.search(last_text)
            h.check("freeze: last-update visible as 'Last update hh:mm:ss'",
                    bool(match) and last.first.is_visible(), f"text {last_text[:60]!r}")
            e0 = elapsed(page)
            title = page.title()
            time.sleep(3.0)
            e1 = elapsed(page)
            h.check("freeze: Elapsed text constant over 3 s while frozen", e0 is not None and e0 == e1,
                    f"Elapsed {e0!r} -> {e1!r}")
            h.check("freeze: tab title starts with the warning sign while reconnecting", title.startswith("⚠"),
                    f"title {title!r}")
            banner = ux.wait_until(lambda: ux.banner_visible(page), 3, 0.2)
            banner_top = page.evaluate(CARD_TOP_JS)
            h.check("banner overlay: transcript-scroll top unchanged (+/- 1 px) when the banner shows",
                    bool(banner) and live_top is not None and banner_top is not None
                    and abs(live_top - banner_top) <= 1,
                    f"banner {bool(banner)}, top before {live_top}, with banner {banner_top}")
            h.shot(page, "i18n-freeze.png")
            os.kill(srv.pid, signal.SIGCONT)
            live = ux.wait_until(lambda: ux.conn_state(page) == "live", 10, 0.2)
            cleared = ux.wait_until(lambda: ux.attr_of(page, '[data-testid="stage-card"]', "data-frozen") != "true", 3, 0.2)
            h.check("freeze resume: SIGCONT returns to live within 10 s and clears data-frozen",
                    bool(live) and bool(cleared), f"conn-state {ux.conn_state(page)!r}, cleared {bool(cleared)}")
        finally:
            ctx.close()
    finally:
        ux.Harness.stop(srv)


# ---- outage: SIGKILL the server, the replay finishes, restart ---------------------------------------
def group_outage(h: ux.Harness, browser: Any) -> None:
    feeds = h.new_feeds("i18n-outage")
    port = h.port + 2
    srv = h.serve(port, feeds, "outage-1")
    srv2 = None
    try:
        before = h.feeds_now(feeds)
        h.start_replay(h.demo_src, feeds, 4, 1, "outage")
        path, _run_id = h.new_run(feeds, before, "outage")
        ctx, page = open_ctx(browser, "en-US")
        try:
            page.goto(h.url(port), wait_until="domcontentloaded", timeout=30000)
            ux.wait_until(lambda: ux.seg_count(page) >= 2, 60, 0.3)
            os.kill(srv.pid, signal.SIGKILL)
            srv.wait(timeout=10)
            lost = ux.wait_until(lambda: ux.conn_state(page) == "reconnecting", 15, 0.3)
            ended = ux.wait_until(lambda: ux.feed_info(path)["ended"], 240, 1.0)
            info = ux.feed_info(path)
            srv2 = h.serve(port, feeds, "outage-2")  # the new server reads the feeds dir afresh
            run_state = ux.wait_until(
                lambda: (page.evaluate(ux.RUN_STATE_JS) or {}).get("state") == "finished", 60, 0.5)
            segs = ux.seg_count(page)
            live = ux.wait_until(lambda: ux.conn_state(page) == "live", 30, 0.3)
            rs = page.evaluate(ux.RUN_STATE_JS) or {}
            h.check("outage: SIGKILL shows reconnecting; after the replay ends and the server restarts the page "
                    "shows run-state finished with segments == feed segments",
                    bool(lost) and bool(ended) and bool(run_state) and segs == info["segments"],
                    f"reconnecting {bool(lost)}, feed ended {bool(ended)}, run-state {rs}, "
                    f"segments {segs} of feed {info['segments']}, live {bool(live)}")
            h.shot(page, "i18n-outage.png")
        finally:
            ctx.close()
    finally:
        ux.Harness.stop(srv)
        ux.Harness.stop(srv2)


GROUP_FUNCS = {"ui": group_ui, "freeze": group_freeze, "outage": group_outage}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="i18n and UI-contract checks for noScribe Live (en, zh-TW).")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="main server port (+1 freeze server, +2 outage server; default: %(default)s)")
    parser.add_argument("--static", default=str(ux.DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=ux.DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, ux._exit_on_term)
    args = parse_args(argv)
    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        print(f"unknown group(s) {unknown}; choose from {','.join(GROUPS)}", file=sys.stderr)
        return 2
    busy = [p for p in (args.port, args.port + 1, args.port + 2) if ux.port_busy(p)]
    if busy:
        print(f"FAIL setup: port(s) {busy} already in use; not touching those processes", flush=True)
        return 2
    h = ux.Harness(args)
    if "static" in groups:
        offenders = static_cjk_scan(LIVE_DIR)
        for line in offenders:
            print(f"  FAIL CJK in string literal: {line}", flush=True)
        h.check("static: no CJK characters in string literals under live/web/src/components and lib",
                not offenders, f"{len(offenders)} offending line(s)" if offenders else "clean")
    ui_groups = [g for g in groups if g in GROUP_FUNCS]
    if ui_groups:
        if not (Path(args.static) / "index.html").is_file():
            print(f"NOTE: {args.static}/index.html is missing; the server serves its placeholder page", flush=True)
        h.prepare_sources()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            print(f"FAIL setup: playwright is not importable with this python: {exc}", flush=True)
            return 2
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for group in ui_groups:
                    print(f"== group {group}", flush=True)
                    try:
                        GROUP_FUNCS[group](h, browser)
                    except Exception as exc:
                        h.check(f"{group}: group completed", False, f"crashed: {exc!r}")
                    finally:
                        h.reap()
            finally:
                browser.close()
    h.cleanup()
    return 0 if h.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
