#!/usr/bin/env python3
"""LLM correction checks for noScribe Live: settings, upload, run, review, export, malformed retry, CORS.

Groups (--only, default all). Each group starts its own `python -m server` on the viewer port, its own mock LLM
(live/stress/mock_llm.py) on the mock port, and its own browser context. The UI contract is the data-testid
set used below (llm-open, llm-panel, llm-settings-open, llm-base-url, llm-api-key, llm-model, llm-remember,
llm-save, llm-test, llm-test-result[data-ok], llm-context-text, llm-files, llm-file[data-status],
llm-context-stats, llm-retrieval-note, llm-run, llm-cancel, llm-progress, llm-error[data-kind], llm-diff
[data-segment-index][data-status][data-corrected-text], llm-accept, llm-reject, llm-accept-all, llm-reject-all,
llm-confirm, llm-confirm-ok, llm-show-original, export-odt, and transcript segments with data-corrected="true").

  settings   save with remember OFF: key in sessionStorage 'noscribe-live-llm-key', not in localStorage;
             test connection ok. Remember ON: key in localStorage.
  upload     the 10 fixtures in live/stress/fixtures/llm go to llm-files: 10 rows with data-status "ok",
             llm-context-stats shows 10.
  run        a correction run on the finished demo feed completes: at least 2 llm-diff rows (the recorded feed
             has 2 correctable segments), one of them for the 吶喊自序 correction (data-corrected-text).
  review     accept one row and reject one (accept two and reject one when there are 3 or more rows): transcript
             shows the accepted corrections (data-corrected="true") and not the originals; reload keeps them
             (IndexedDB); llm-show-original hides them, again shows.
  export     Download .odt (export-odt): zip with mimetype first, content.xml holds an accepted corrected
             string and the AI-correction note.
  malformed  model "mock-malformed-once": the first answer per batch is invalid JSON; the run still completes
             and the mock log shows a malformed answer followed by a valid retry.
  cors       mock started with --no-cors: llm-test shows llm-error[data-kind="cors"]; a correction run does too.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_llm.py [--only settings,upload,run,review,export,malformed,cors]
        [--port 8960] [--static DIR] [--python PY] [--work DIR]

Viewer port of group i is --port + i (settings 0, upload 1, run 2, review 3, export 4, malformed 5, cors 6);
its mock listens on --port + 20 + i. To use the mock by hand: `python3 live/stress/mock_llm.py --port 8799`,
base URL http://localhost:8799/v1, any API key, model "mock". WORK (default /tmp/nslive-llm) holds feeds/,
logs/, shots/ and downloads/. The finished demo feed is read only. Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import signal
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # live/stress
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  shared harness: servers, processes, reporting

MOCK = HERE / "mock_llm.py"
FIX_DIR = HERE / "fixtures" / "llm"
FIXTURES = sorted(FIX_DIR.glob("ref-*.docx")) + sorted(FIX_DIR.glob("ref-*.pdf"))
FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261022-003524-demo-en-zh.ndjson")  # read only
DEMO_NAME = FEED_SRC.name
DEFAULT_PORT = 8960
DEFAULT_WORK = Path("/tmp/nslive-llm")
KEY_STORE = "noscribe-live-llm-key"
GROUP_OFFSET = {"settings": 0, "upload": 1, "run": 2, "review": 3, "export": 4, "malformed": 5, "cors": 6}
GROUPS = tuple(GROUP_OFFSET)
MOCK_OFFSET = 20
CORRECTED = '[data-corrected="true"]'
MIN_DIFF_ROWS = 2  # the recorded demo feed has 2 correctable segments


def T(name: str) -> str:
    return f'[data-testid="{name}"]'


ALL_STORAGE_JS = "() => JSON.stringify(Object.assign({}, window.localStorage))"


@dataclass
class Stack:
    viewer: Any
    mock: Any
    mock_port: int
    run_id: str
    mock_log: Path

    @property
    def base(self) -> str:
        return f"http://localhost:{self.mock_port}/v1"


def has_num(text: str, n: int) -> bool:
    return re.search(rf"(?<!\d){n}(?!\d)", text or "") is not None


def mock_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_stack(h: Any, tag: str, mock_args: tuple[str, ...] = ()) -> Stack:
    feeds = h.new_feeds(tag)
    shutil.copyfile(h.demo_src, feeds / DEMO_NAME)
    viewer = h.serve(h.port, feeds, tag)
    mport = h.port + MOCK_OFFSET
    mock_log = h.logs / f"mock-{tag}.log"
    cmd = [sys.executable, "-I", "-B", str(MOCK), "--port", str(mport), "--log", str(mock_log), *mock_args]
    mock = h._spawn(cmd, f"mock-{tag}-{mport}.out")
    if not ux.wait_until(lambda: mock_up(mport), 15):
        raise RuntimeError(f"mock LLM on port {mport} did not answer /v1/models (logs in {h.logs})")
    run_id = ux.feed_info(feeds / DEMO_NAME)["run_id"]
    return Stack(viewer, mock, mport, run_id, mock_log)


def open_run(page: Any, port: int, run_id: str) -> None:
    page.goto(f"http://127.0.0.1:{port}/?run={run_id}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(T("llm-open"), timeout=30000)


def open_panel(page: Any) -> None:
    if not page.is_visible(T("llm-panel")):
        page.click(T("llm-open"))
    page.wait_for_selector(T("llm-panel"), state="visible", timeout=15000)


def close_panel(page: Any) -> None:
    """Closes the LLM panel with Escape, so the transcript behind it can be clicked. Twice at most: a settings
    dialog on top of the panel closes first."""
    for _ in range(2):
        if not page.is_visible(T("llm-panel")):
            break
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    page.wait_for_selector(T("llm-panel"), state="hidden", timeout=10000)


def configure(page: Any, base: str, key: str, model: str, remember: bool = False) -> None:
    open_panel(page)
    page.click(T("llm-settings-open"))
    page.wait_for_selector(T("llm-base-url"), state="visible", timeout=15000)
    page.fill(T("llm-base-url"), base)
    page.fill(T("llm-api-key"), key)
    page.fill(T("llm-model"), model)
    box = page.locator(T("llm-remember"))
    if remember:
        box.check()
    else:
        box.uncheck()
    page.click(T("llm-save"))
    page.wait_for_timeout(300)
    if page.is_visible(T("llm-base-url")):  # the dialog stays open after save: close it
        page.keyboard.press("Escape")


def click_test(page: Any) -> None:
    """Clicks the settings dialog's test button, opening the dialog first when it is closed. The dialog animates in,
    so the button can be moving or re-mounted for a moment: let the animation settle, then click with a fresh locator
    on each attempt, and fall back to a DOM click last."""
    if not page.is_visible(T("llm-test")):
        page.click(T("llm-settings-open"))
        page.wait_for_selector(T("llm-test"), state="visible", timeout=15000)
    page.wait_for_timeout(500)
    last: Exception | None = None
    for attempt in range(4):
        try:
            if attempt < 3:
                page.locator(T("llm-test")).click(timeout=4000)
            else:
                page.locator(T("llm-test")).evaluate("el => el.click()")
            return
        except Exception as exc:  # not stable or detached: retry with a fresh locator
            last = exc
            page.wait_for_timeout(400)
    raise RuntimeError(f"could not click llm-test: {last!r}")


def upload_fixtures(page: Any) -> bool:
    open_panel(page)
    page.set_input_files(T("llm-files"), [str(p) for p in FIXTURES])
    ok_rows = f'{T("llm-file")}[data-status="ok"]'
    return bool(ux.wait_until(lambda: page.locator(ok_rows).count() >= len(FIXTURES), 90, 0.5))


def run_correction(page: Any, timeout: float = 90) -> int:
    page.click(T("llm-run"))
    ux.wait_until(lambda: page.locator(T("llm-diff")).count() >= MIN_DIFF_ROWS, timeout, 0.5)
    return page.locator(T("llm-diff")).count()


def prepare(page: Any, base: str, key: str, model: str) -> int:
    """Configure, upload the 10 fixtures, run the correction; returns the number of llm-diff rows."""
    configure(page, base, key, model)
    upload_fixtures(page)
    return run_correction(page)


def text_of(page: Any, selector: str) -> str | None:
    loc = page.locator(selector)
    return loc.first.inner_text() if loc.count() else None


def info(name: str, detail: str) -> None:
    print(f"INFO {name}: {detail}", flush=True)


def stop_all(*procs: Any) -> None:
    for proc in procs:
        ux.Harness.stop(proc)


# ---- groups ----------------------------------------------------------------------------------------
def group_settings(h: Any, browser: Any) -> None:
    st = start_stack(h, "settings")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        key_off = "sk-llm-test-OFF-1111"
        configure(page, st.base, key_off, "mock", remember=False)
        session_val = page.evaluate(f"() => sessionStorage.getItem('{KEY_STORE}')")
        local_off = page.evaluate(ALL_STORAGE_JS)
        h.check("settings: remember OFF keeps the key in sessionStorage 'noscribe-live-llm-key'",
                session_val == key_off, f"sessionStorage has the key: {session_val == key_off}")
        h.check("settings: remember OFF keeps the key out of localStorage", key_off not in local_off,
                f"localStorage holds {len(local_off)} chars, key present {key_off in local_off}")
        click_test(page)
        ok = page.locator(f'{T("llm-test-result")}[data-ok="true"]')
        good = ux.wait_until(lambda: ok.count() > 0, 25, 0.3)
        h.check("settings: test connection ok", bool(good), f"llm-test-result[data-ok=true] seen {bool(good)}")
        ctx2, page2 = h.new_page(browser)
        ctxs.append(ctx2)
        open_run(page2, h.port, st.run_id)
        key_on = "sk-llm-test-ON-2222"
        configure(page2, st.base, key_on, "mock", remember=True)
        local_on = page2.evaluate(ALL_STORAGE_JS)
        h.check("settings: remember ON stores the key in localStorage", key_on in local_on,
                f"key in localStorage {key_on in local_on}")
        h.shot(page2, "settings-remember-on.png")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_upload(h: Any, browser: Any) -> None:
    st = start_stack(h, "upload")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        configure(page, st.base, "sk-llm-test-UP-7777", "mock")
        all_ok = upload_fixtures(page)
        statuses = page.locator(T("llm-file")).evaluate_all("els => els.map((e) => e.getAttribute('data-status'))")
        h.check("upload: 10 fixtures, all rows status ok",
                all_ok and len(statuses) == len(FIXTURES) == 10 and all(s == "ok" for s in statuses),
                f"fixtures {len(FIXTURES)}, rows {len(statuses)}, statuses {sorted(set(statuses))}")
        stats = text_of(page, T("llm-context-stats")) or ""
        h.check("upload: llm-context-stats shows 10 files", has_num(stats, 10), f"stats {stats!r}")
        info("upload: retrieval note", repr(text_of(page, T("llm-retrieval-note"))))
        h.shot(page, "upload-rows.png")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_run(h: Any, browser: Any) -> None:
    st = start_stack(h, "run")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        count = prepare(page, st.base, "sk-llm-test-RUN-3333", "mock")
        h.check("run: correction run completes with at least 2 llm-diff rows", count >= MIN_DIFF_ROWS,
                f"llm-diff rows {count}")
        nahan = page.locator(f'{T("llm-diff")}[data-corrected-text*="吶喊自序"]').count()
        h.check("run: one of the rows is the 吶喊自序 correction", nahan > 0,
                f"rows whose corrected text has 吶喊自序: {nahan}")
        errors = page.locator(T("llm-error")).count()
        h.check("run: no llm-error shown", errors == 0, f"llm-error elements {errors}")
        h.shot(page, "run-diffs.png")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_review(h: Any, browser: Any) -> None:
    st = start_stack(h, "review")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        count = prepare(page, st.base, "sk-llm-test-REV-4444", "mock")
        if count < MIN_DIFF_ROWS:
            h.check("review: run produced at least 2 rows first", False, f"llm-diff rows {count}")
            return
        # The recorded feed has 2 rows: accept the first, reject the second. With 3 or more rows: accept the first
        # two, reject the third.
        accept_rows = [0, 1] if count >= 3 else [0]
        reject_row = 2 if count >= 3 else 1
        n_acc = len(accept_rows)
        rows = page.locator(T("llm-diff"))
        for i in accept_rows:
            rows.nth(i).locator(T("llm-accept")).click()
        rows.nth(reject_row).locator(T("llm-reject")).click()
        statuses = [rows.nth(i).get_attribute("data-status") or "" for i in [*accept_rows, reject_row]]
        marked = all("accept" in s for s in statuses[:-1]) and "reject" in statuses[-1]
        h.check("review: accept and reject mark the rows", marked, f"statuses {statuses}")
        close_panel(page)  # the transcript checks below run with the panel closed
        shown = ux.wait_until(lambda: page.locator(CORRECTED).count() >= n_acc, 15, 0.3)
        texts = page.locator(CORRECTED).all_inner_texts()
        originals_gone = not any(("LibriVox dot org" in t) or ("吶喊自恤" in t) for t in texts)
        h.check("review: transcript shows the accepted corrections (data-corrected) and not the originals",
                bool(shown) and originals_gone, f"corrected segments {len(texts)}; originals gone {originals_gone}")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector(T("llm-open"), timeout=30000)
        after = ux.wait_until(lambda: page.locator(CORRECTED).count() >= n_acc, 20, 0.3)
        open_panel(page)
        rows2 = page.locator(T("llm-diff"))
        p_acc = rows2.nth(accept_rows[0]).get_attribute("data-status") or ""
        p_rej = rows2.nth(reject_row).get_attribute("data-status") or ""
        h.check("review: corrections persist after reload (IndexedDB)",
                bool(after) and "accept" in p_acc and "reject" in p_rej,
                f"corrected after reload {page.locator(CORRECTED).count()}; statuses {p_acc!r} {p_rej!r}")
        page.click(T("llm-show-original"))  # inside the panel
        close_panel(page)
        hidden = ux.wait_until(lambda: page.locator(CORRECTED).count() == 0, 10, 0.3)
        h.check("review: llm-show-original shows the original text", bool(hidden),
                f"corrected segments while original shown {page.locator(CORRECTED).count()}")
        open_panel(page)
        page.click(T("llm-show-original"))
        close_panel(page)
        back = ux.wait_until(lambda: page.locator(CORRECTED).count() >= n_acc, 10, 0.3)
        h.check("review: toggling again shows the corrections", bool(back),
                f"corrected segments {page.locator(CORRECTED).count()}")
        h.shot(page, "review-accepted.png")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_export(h: Any, browser: Any) -> None:
    st = start_stack(h, "export")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        count = prepare(page, st.base, "sk-llm-test-EXP-8888", "mock")
        rows = page.locator(T("llm-diff"))
        libri = next((i for i in range(rows.count()) if "LibriVox" in rows.nth(i).inner_text()), 0)
        rows.nth(libri).locator(T("llm-accept")).click()
        ux.wait_until(lambda: page.locator(CORRECTED).count() >= 1, 15, 0.3)
        close_panel(page)  # the open panel covers the transcript, and export-odt is in the transcript view
        target = h.work / "downloads" / f"export-{ux.STAMP}.odt"
        target.parent.mkdir(parents=True, exist_ok=True)
        with page.expect_download(timeout=60000) as dl_info:
            page.click(T("export-odt"))
        dl_info.value.save_as(str(target))
        with zipfile.ZipFile(target) as zf:
            first = zf.infolist()[0].filename
            mimetype = zf.read("mimetype").decode("ascii", "replace").strip()
            xml = zf.read("content.xml").decode("utf-8")
        h.check("export: zip has mimetype as the first entry",
                first == "mimetype" and mimetype == "application/vnd.oasis.opendocument.text",
                f"first entry {first!r}, mimetype {mimetype!r}; llm-diff rows {count}")
        marker = "LibriVox.org"
        h.check("export: content.xml holds the accepted corrected string", marker in xml,
                f"'{marker}' in content.xml: {marker in xml}; accepted row index {libri}")
        note = any(k in xml for k in ("AI", "LLM", "校正"))
        h.check("export: content.xml carries the AI-correction note", note, f"note markers present: {note}")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_malformed(h: Any, browser: Any) -> None:
    st = start_stack(h, "malformed")
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        count = prepare(page, st.base, "sk-llm-test-MAL-5555", "mock-malformed-once")
        h.check("malformed: run still completes after an invalid JSON answer (retry)", count >= MIN_DIFF_ROWS,
                f"llm-diff rows {count}")
        log = st.mock_log.read_text(encoding="utf-8") if st.mock_log.exists() else ""
        mal, retry = log.count("response=malformed"), log.count("response=valid-retry")
        h.check("malformed: mock answered malformed first, then a valid retry", mal >= 1 and retry >= 1,
                f"malformed answers {mal}, valid retries {retry}")
        errors = page.locator(T("llm-error")).count()
        h.check("malformed: no llm-error shown", errors == 0, f"llm-error elements {errors}")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_cors(h: Any, browser: Any) -> None:
    st = start_stack(h, "cors", mock_args=("--no-cors",))
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser)
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        configure(page, st.base, "sk-llm-test-COR-6666", "mock")
        click_test(page)
        cors = page.locator(f'{T("llm-error")}[data-kind="cors"]')
        seen = ux.wait_until(lambda: cors.count() > 0 and cors.first.is_visible(), 25, 0.3)
        h.check("cors: a mock without CORS headers shows llm-error[data-kind=cors]", bool(seen),
                f"cors error elements {cors.count()}")
        h.shot(page, "cors-error.png")
        # The same failure from a correction run. Reload first, so the settings test result is gone and only the
        # run's error can match; the saved settings survive the reload.
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector(T("llm-open"), timeout=30000)
        open_panel(page)
        try:
            page.click(T("llm-run"), timeout=10000)
            run_seen = ux.wait_until(lambda: cors.count() > 0 and cors.first.is_visible(), 30, 0.3)
            run_detail = f"cors error elements {cors.count()}"
        except Exception as exc:  # the run could not start: a failed check, not a crash of the group
            run_seen, run_detail = False, f"run not started: {exc!r}"[:200]
        h.check("cors: a correction run shows llm-error[data-kind=cors] too", bool(run_seen), run_detail)
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


GROUP_FUNCS = {"settings": group_settings, "upload": group_upload, "run": group_run, "review": group_review,
               "export": group_export, "malformed": group_malformed, "cors": group_cors}


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _exit_on_term)
    parser = argparse.ArgumentParser(description="LLM correction checks for noScribe Live.")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of groups: " + ",".join(GROUPS))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="base port: group i viewer on +i, its mock on +20+i")
    parser.add_argument("--static", default=str(ux.DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--python", default=ux.DEFAULT_PY, help="python with the server deps (live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs, downloads")
    args = parser.parse_args(argv)

    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUP_OFFSET]
    if unknown:
        parser.error(f"unknown group(s) {unknown}; choose from {','.join(GROUPS)}")
    if len(FIXTURES) != 10:
        parser.error(f"expected 10 fixtures in {FIX_DIR}, found {len(FIXTURES)} (run make_fixtures.py)")
    if not FEED_SRC.is_file():
        parser.error(f"demo feed missing: {FEED_SRC}")
    busy = [p for g in groups for p in (args.port + GROUP_OFFSET[g], args.port + MOCK_OFFSET + GROUP_OFFSET[g])
            if ux.port_busy(p)]
    if busy:
        print(f"FAIL setup: port(s) {busy} already in use; not touching those processes", flush=True)
        return 2
    if not (Path(args.static) / "index.html").is_file():
        print(f"NOTE: {args.static}/index.html is missing; the server serves its placeholder page", flush=True)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    h = ux.Harness(args)
    h.demo_src = h.src / DEMO_NAME
    shutil.copyfile(FEED_SRC, h.demo_src)
    (h.work / "downloads").mkdir(parents=True, exist_ok=True)
    print(f"sources: {DEMO_NAME} copied to {h.src}; fixtures: {len(FIXTURES)} in {FIX_DIR}", flush=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for group in groups:
                    h.port = args.port + GROUP_OFFSET[group]
                    print(f"== group {group} (viewer port {h.port}, mock port {h.port + MOCK_OFFSET})", flush=True)
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
