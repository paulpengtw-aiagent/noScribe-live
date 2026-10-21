#!/usr/bin/env python3
"""Transcription-complete dialog and CLI log checks for noScribe Live.

Groups (--only, default all):
  complete  desktop 1440x900, follow newest, page open before a replay at speed 2 (max-gap 30). After run_end and a
            few seconds the dialog is visible; its text has the length (m:ss of the feed's audio duration), the
            segment count and the speaker count. Focus is inside it; six Tab presses keep it inside; Esc closes it;
            it does not come back for the same run within 5 s. Reopen: a second replay opens it again and Download
            saves an .odt (a zip whose first entry is mimetype). A third replay: Keep viewing closes it.
  history   a finished run opened bare and with ?run=<id> shows no dialog within 5 s. The failed fixture replayed
            while the page watches: no dialog.
  easy      Easy view (noscribe-live-easy=1): dialog buttons >= 48 px tall, dialog text >= 20 px.
  phonelog  390x844, a finished run with CLI log lines: [data-testid=cli-log] visible and open by default, its scroll
            body shows at most 6 lines, cli-log-expand grows it to >= 1.3x and back. At 1440 there is no expand button.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_dialog.py [--only complete,history,easy,phonelog] [--port 8950]
        [--static DIR] [--python PY] [--work DIR]

Ports: complete --port, history +1, easy +2, phonelog +3. Each group starts its own `python -m server` and its own
replays through the Harness in test_ux.py. WORK (default /tmp/nslive-dialog) holds src/ (copies of the demo feed and
the failed fixture; the originals are read only), feeds/, logs/, shots/ and downloads/. Exit code 0 only if every
check passed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  shared harness: servers, replays, reporting

FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261022-003524-demo-en-zh.ndjson")  # read only
FAILED_SRC = HERE / "fixtures" / "failed-run.ndjson"  # read only
DEFAULT_WORK = Path("/tmp/nslive-dialog")
DEFAULT_PORT = 8950
GROUPS = ("complete", "history", "easy", "phonelog")
GROUP_PORT = {"complete": 0, "history": 1, "easy": 2, "phonelog": 3}
RUN_END_RE = re.compile(r'"type":\s*"run_end"')
DESKTOP = (1440, 900)
PHONE = (390, 844)

DIALOG_OPEN_JS = r"""() => { const d = document.querySelector('[data-testid="run-complete-dialog"]');
  if (!d) return false; const r = d.getBoundingClientRect(); const cs = getComputedStyle(d);
  return r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; }"""

DIALOG_FOCUS_JS = r"""() => { const d = document.querySelector('[data-testid="run-complete-dialog"]');
  return !!d && d.contains(document.activeElement); }"""

DIALOG_STATS_JS = r"""() => { const e = document.querySelector('[data-testid="run-complete-stats"]');
  return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; }"""

EASY_JS = r"""() => { const d = document.querySelector('[data-testid="run-complete-dialog"]');
  if (!d) return null;
  const btns = Array.from(d.querySelectorAll('button')).map((b) => ({ id: b.getAttribute('data-testid') || '',
    text: b.textContent.trim(), h: b.getBoundingClientRect().height, fs: parseFloat(getComputedStyle(b).fontSize) }));
  const texts = Array.from(d.querySelectorAll('h1, h2, p, li')).filter((e) => e.textContent.trim())
    .map((e) => ({ tag: e.tagName, fs: parseFloat(getComputedStyle(e).fontSize), text: e.textContent.trim().slice(0, 40) }));
  return { btns, texts, easyKey: localStorage.getItem('noscribe-live-easy') }; }"""

CLI_JS = r"""() => {
  const root = document.querySelector('[data-testid="cli-log"]');
  if (!root) return null;
  const region = root.querySelector('[role="region"]');
  const toggle = root.querySelector('button[aria-controls]');
  const exp = root.querySelector('[data-testid="cli-log-expand"]');
  const r = region ? region.getBoundingClientRect() : null;
  const er = exp ? exp.getBoundingClientRect() : null;
  return {
    open: toggle ? toggle.getAttribute('aria-expanded') : null,
    h: r ? r.height : 0,
    lineH: region ? parseFloat(getComputedStyle(region).lineHeight) || 0 : 0,
    lines: region ? region.children.length : 0,
    expExists: !!exp,
    expVisible: !!exp && !!er && er.height > 0 && getComputedStyle(exp).display !== 'none',
    expText: exp ? exp.textContent.trim() : null,
  };
}"""


def info(name: str, detail: str) -> None:
    print(f"INFO {name}: {detail}", flush=True)


def poll(fn: Any, timeout: float, step: float = 0.2) -> Any:
    end = time.time() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.time() >= end:
            return None
        time.sleep(step)


def clock(seconds: float) -> str:
    """lib/format.ts formatClock: mm:ss, or h:mm:ss from one hour."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def has_num(text: str, n: int) -> bool:
    return re.search(rf"(?<!\d){n}(?!\d)", text) is not None


def feed_facts(path: Path) -> dict[str, Any]:
    """Audio duration (the audio event), segment count and speaker count of a feed file."""
    duration: float | None = None
    segments = 0
    speakers: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "audio" and duration is None:
            duration = float(ev["duration"])
        elif ev.get("type") == "segment":
            segments += 1
            speakers.add(str(ev.get("speaker")))
    return {"duration": duration or 0.0, "segments": segments, "speakers": len(speakers)}


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


def replay(h: Any, src: Path, feeds: Path, tag: str, speed: float = 2, max_gap: float = 30) -> tuple[Path, str, bool]:
    """Start a replay of src; returns (feed path, run id, whether run_end was seen)."""
    before = h.feeds_now(feeds)
    h.start_replay(src, feeds, speed, max_gap, tag)
    path, run_id = h.new_run(feeds, before, tag)
    ended = run_end_at(path, 150) is not None
    return path, run_id, ended


def preset(theme: str, locale: str, easy: bool = False) -> str:
    parts = [f"localStorage.setItem('noscribe-live-theme', {json.dumps(theme)});",
             f"localStorage.setItem('noscribe-live-locale', {json.dumps(locale)});"]
    if easy:
        parts.append("localStorage.setItem('noscribe-live-easy', '1');")
    return "try { " + " ".join(parts) + " } catch (e) {}"


def new_ctx(browser: Any, w: int = 1440, hgt: int = 900, presets: str | None = None) -> tuple[Any, Any]:
    ctx = browser.new_context(viewport={"width": w, "height": hgt})
    ctx.add_init_script(ux.INIT_JS)
    if presets:
        ctx.add_init_script(presets)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    return ctx, page


def dialog_open(page: Any) -> bool:
    return bool(page.evaluate(DIALOG_OPEN_JS))


def wait_dialog(page: Any, timeout: float) -> bool:
    return bool(poll(lambda: dialog_open(page), timeout, 0.25))


def quiet_for(page: Any, seconds: float) -> bool:
    """True when no dialog shows on the page for the whole window."""
    end = time.time() + seconds
    while time.time() < end:
        if dialog_open(page):
            return False
        time.sleep(0.25)
    return True


def download_check(h: Any, page: Any, run_id: str) -> None:
    dest_dir = h.work / "downloads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name_ok = "Download saves an .odt whose zip starts with mimetype"
    try:
        with page.expect_download(timeout=30000) as info_dl:
            page.locator('[data-testid="run-complete-download"]').click()
        dl = info_dl.value
        suggested = dl.suggested_filename
        dest = dest_dir / f"{run_id}.odt"
        dl.save_as(str(dest))
        try:
            first = zipfile.ZipFile(dest).namelist()[0]
        except (zipfile.BadZipFile, IndexError, OSError) as exc:
            first = f"unreadable ({exc.__class__.__name__})"
        h.check(f"complete: {name_ok}", suggested.endswith(".odt") and first == "mimetype",
                f"suggested name {suggested!r}; first zip entry {first!r}; saved {dest}")
    except Exception as exc:
        text = str(exc).splitlines()[0][:160] if str(exc) else ""
        h.check(f"complete: {name_ok}", False, f"download failed: {exc.__class__.__name__}: {text}")
    closed = bool(poll(lambda: not dialog_open(page), 10, 0.2))
    h.check("complete: the dialog closes after a successful download", closed, f"closed {closed}")


def group_complete(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("complete")
    srv = h.serve(h.port, feeds, "complete")
    ctxs: list[Any] = []
    try:
        facts = feed_facts(h.demo_src)
        length = clock(facts["duration"])
        ctx, page = new_ctx(browser, *DESKTOP, presets=preset("dark", "en"))
        ctxs.append(ctx)
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.5)  # the page is open before the run starts
        _path, run_id, ended = replay(h, h.demo_src, feeds, "complete")
        time.sleep(3.0)  # run_end, then a few seconds
        shown = wait_dialog(page, 20)
        h.check("complete: dialog visible after run_end (1440x900, page open before the replay)", shown,
                f"run {run_id}; run_end seen {ended}")
        if shown:
            h.shot(page, "dialog-complete-1440-en.png")
        stats = page.evaluate(DIALOG_STATS_JS) or ""
        found = {"length": length in stats, "segments": has_num(stats, facts["segments"]),
                 "speakers": has_num(stats, facts["speakers"])}
        h.check("complete: text shows the length, segment count and speaker count", shown and all(found.values()),
                f"expected length {length}, {facts['segments']} segments, {facts['speakers']} speakers (from the "
                f"feed); found {found}; text {stats!r}")
        focus = bool(poll(lambda: page.evaluate(DIALOG_FOCUS_JS), 3, 0.2))
        h.check("complete: focus is inside the dialog when it opens", shown and focus,
                f"document.activeElement inside the dialog: {focus}")
        trapped: list[bool] = []
        for _ in range(6):
            page.keyboard.press("Tab")
            time.sleep(0.1)
            trapped.append(bool(page.evaluate(DIALOG_FOCUS_JS)))
        h.check("complete: six Tab presses keep focus inside the dialog", shown and all(trapped),
                f"focus inside after each Tab: {trapped}")
        page.keyboard.press("Escape")
        closed = bool(poll(lambda: not dialog_open(page), 5, 0.2))
        h.check("complete: Esc closes the dialog", shown and closed, f"closed {closed}")
        back = not quiet_for(page, 5)
        h.check("complete: the dialog does not come back for the same run within 5 s", shown and not back,
                f"reappeared {back}")

        _p2, run2, ended2 = replay(h, h.demo_src, feeds, "complete-reopen")
        time.sleep(3.0)
        reopened = wait_dialog(page, 20)
        h.check("complete: a second run opens the dialog again", reopened and run2 != run_id,
                f"second run {run2}; run_end seen {ended2}; visible {reopened}")
        if reopened:
            download_check(h, page, run2)

        _p3, run3, ended3 = replay(h, h.demo_src, feeds, "complete-keep")
        time.sleep(3.0)
        visible3 = wait_dialog(page, 20)
        if visible3:
            page.locator('[data-testid="run-complete-keep"]').click()
        gone = bool(poll(lambda: not dialog_open(page), 5, 0.2))
        h.check("complete: Keep viewing closes the dialog", visible3 and gone,
                f"third run {run3}; run_end seen {ended3}; visible {visible3}; closed {gone}")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


def group_history(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("history")
    srv = h.serve(h.port, feeds, "history")
    ctxs: list[Any] = []
    try:
        url = h.url(h.port)
        _path, run_id, ended = replay(h, h.demo_src, feeds, "history")  # finished before any page opens
        time.sleep(2.0)
        ctx, bare = new_ctx(browser, presets=preset("dark", "en"))
        ctxs.append(ctx)
        bare.goto(url, wait_until="domcontentloaded", timeout=30000)
        quiet_bare = quiet_for(bare, 5)
        h.check("history: a finished run opened bare shows no dialog within 5 s", quiet_bare and ended,
                f"run {run_id}; run_end seen {ended}; no dialog {quiet_bare}")
        ctx2, by_id = new_ctx(browser, presets=preset("dark", "en"))
        ctxs.append(ctx2)
        by_id.goto(url + f"?run={run_id}", wait_until="domcontentloaded", timeout=30000)
        quiet_id = quiet_for(by_id, 5)
        h.check("history: ?run=<id> of a finished run shows no dialog within 5 s", quiet_id and ended,
                f"no dialog {quiet_id}")
        ctx3, watch = new_ctx(browser, presets=preset("dark", "en"))
        ctxs.append(ctx3)
        watch.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.5)  # the page is open before the failed run starts
        _pf, failed_id, failed_ended = replay(h, h.failed_src, feeds, "history-failed")
        quiet_failed = quiet_for(watch, 5)
        info("history: failed fixture", f"run {failed_id} status {h.api_status(h.port, failed_id)!r}")
        h.check("history: a failed run watched live shows no dialog", quiet_failed and failed_ended,
                f"run_end seen {failed_ended}; no dialog {quiet_failed}")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


def group_easy(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("easy")
    srv = h.serve(h.port, feeds, "easy")
    ctxs: list[Any] = []
    try:
        ctx, page = new_ctx(browser, presets=preset("dark", "en", easy=True))
        ctxs.append(ctx)
        page.goto(h.url(h.port), wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.5)
        _path, run_id, ended = replay(h, h.demo_src, feeds, "easy")
        time.sleep(3.0)
        shown = wait_dialog(page, 20)
        m = page.evaluate(EASY_JS) or {"btns": [], "texts": [], "easyKey": None}
        h.check("easy: dialog visible in Easy view", shown,
                f"noscribe-live-easy={m.get('easyKey')!r}; run {run_id}; run_end seen {ended}")
        btns = m["btns"]
        texts = m["texts"]
        h.check("easy: dialog buttons >= 48 px tall", shown and bool(btns) and all(b["h"] >= 48 for b in btns),
                "buttons " + ", ".join(f"{b['text']!r} {b['h']:.0f} px" for b in btns))
        fonts = [t["fs"] for t in texts] + [b["fs"] for b in btns]
        h.check("easy: dialog text >= 20 px", shown and bool(fonts) and min(fonts) >= 20,
                f"smallest font {min(fonts) if fonts else None} px over {len(fonts)} text elements")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


def group_phonelog(h: Any, browser: Any) -> None:
    feeds = h.new_feeds("phonelog")
    srv = h.serve(h.port, feeds, "phonelog")
    ctxs: list[Any] = []
    try:
        _path, run_id, ended = replay(h, h.demo_src, feeds, "phonelog")  # a finished run with log events
        time.sleep(2.0)
        url = h.url(h.port) + f"?run={run_id}"
        ctx, page = new_ctx(browser, *PHONE, presets=preset("dark", "en"))
        ctxs.append(ctx)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        m0 = poll(lambda: page.evaluate(CLI_JS), 30, 0.3) or {}
        vis = m0.get("h", 0) > 0
        h.check("phonelog 390x844: [data-testid=cli-log] visible on a finished run", vis,
                f"run {run_id}; run_end seen {ended}; body {m0.get('h', 0):.0f} px; {m0.get('lines', 0)} lines")
        h.check("phonelog 390x844: the panel is open by default", m0.get("open") == "true",
                f"aria-expanded {m0.get('open')!r}")
        limit = 6 * (m0.get("lineH") or 24) + 8  # six lines at 24 px plus the 8 px bottom padding
        h.check("phonelog 390x844: scroll body shows at most 6 lines", vis and m0["h"] <= limit + 2,
                f"body {m0.get('h', 0):.0f} px; six lines = {limit:.0f} px")
        h.shot(page, "phonelog-390-finished.png")
        btn = page.locator('[data-testid="cli-log-expand"]')
        btn.click(timeout=5000)
        time.sleep(0.5)
        m1 = page.evaluate(CLI_JS) or {}
        btn.click(timeout=5000)
        time.sleep(0.5)
        m2 = page.evaluate(CLI_JS) or {}
        h0, h1, h2 = m0.get("h", 0), m1.get("h", 0), m2.get("h", 0)
        h.check("phonelog 390x844: expand grows the body to >= 1.3x and collapse returns it",
                vis and h0 > 0 and h1 >= 1.3 * h0 and h2 <= 1.05 * h0,
                f"collapsed {h0:.0f} px, expanded {h1:.0f} px ({m1.get('expText')!r}), collapsed again {h2:.0f} px")
        ctx2, wide = new_ctx(browser, *DESKTOP, presets=preset("dark", "en"))
        ctxs.append(ctx2)
        wide.goto(url, wait_until="domcontentloaded", timeout=30000)
        mw = poll(lambda: wide.evaluate(CLI_JS), 30, 0.3) or {}
        expand_visible = bool(mw.get("expVisible"))
        h.check("phonelog 1440x900: no expand button", mw.get("h", 0) > 0 and not expand_visible,
                f"cli-log body {mw.get('h', 0):.0f} px; expand element exists {mw.get('expExists')}, "
                f"visible {expand_visible}")
    finally:
        for ctx in ctxs:
            ctx.close()
        h.stop(srv)


GROUP_FUNCS = {"complete": group_complete, "history": group_history, "easy": group_easy,
               "phonelog": group_phonelog}


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, ux._exit_on_term)
    parser = argparse.ArgumentParser(description="Transcription-complete dialog and CLI log checks for noScribe Live.")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="base port: complete +0, history +1, easy +2, phonelog +3")
    parser.add_argument("--static", default=str(ux.DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=ux.DEFAULT_PY, help="python with the server deps (live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs, downloads")
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
    h.demo_src = h.src / FEED_SRC.name
    shutil.copyfile(FEED_SRC, h.demo_src)
    h.failed_src = h.src / FAILED_SRC.name
    shutil.copyfile(FAILED_SRC, h.failed_src)
    print(f"sources: {FEED_SRC.name} and {FAILED_SRC.name} copied to {h.src}", flush=True)
    try:
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
