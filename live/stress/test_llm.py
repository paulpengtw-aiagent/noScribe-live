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
             The regular mock log shows browser_header=no for its chat requests (Ollama-style hosts get no header).
  review     accept one row and reject one (accept two and reject one when there are 3 or more rows): transcript
             shows the accepted corrections (data-corrected="true") and not the originals; reload keeps them
             (IndexedDB); llm-show-original hides them, again shows.
  export     Download .odt (export-odt): zip with mimetype first, content.xml holds an accepted corrected
             string and the AI-correction note.
  malformed  model "mock-malformed-once": the first answer per batch is invalid JSON; the run still completes
             and the mock log shows a malformed answer followed by a valid retry.
  cors       mock started with --no-cors: llm-test shows llm-error[data-kind="cors"]; a correction run does too.
  anthropic  mock started with --anthropic and the test-only Anthropic override (anthropic_override): the preset
             fills base URL + model and shows the note (the real URL is never contacted); the mock typed by hand,
             key sk-ant-test: test connection ok, provider anthropic, model listed, and the mock log shows
             GET /v1/models with browser_header=yes auth=x-api-key; key sk-ant-nomodel: data-model-listed=false;
             a run without uploads gets at least 2 llm-diff rows and no llm-error, its chat requests carry
             browser_header=yes, no temperature/top_p/response_format and max_tokens >= 16000; without the override
             the same mock gives llm-error[data-kind="cors"].
  anthropic-errors  the same mock: keys sk-ant-401/403/429/529 via test connection give data-kind auth, forbidden,
             rate_limit and overloaded.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/test_llm.py [--only settings,upload,run,review,export,malformed,cors,anthropic,anthropic-errors]
        [--port 8960] [--static DIR] [--python PY] [--work DIR]

Viewer port of group i is --port + i (settings 0, upload 1, run 2, review 3, export 4, malformed 5, cors 6,
anthropic 7, anthropic-errors 8);
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
GROUP_OFFSET = {"settings": 0, "upload": 1, "run": 2, "review": 3, "export": 4, "malformed": 5, "cors": 6,
                "anthropic": 7, "anthropic-errors": 8}
ANTHROPIC_BASE = "https://api.anthropic.com/v1"  # the preset; never test-connected (the checks use the mock)
ANTHROPIC_MODEL = "claude-opus-5-5"
ANTHROPIC_HOSTS_KEY = "noscribe-live-llm-dev-anthropic-hosts"  # test-only override of the Anthropic host detection
ANTHROPIC_PROBE = {"x-api-key": "sk-ant-ready", "anthropic-version": "2023-06-01"}  # readiness GET of --anthropic
ANTHROPIC_ERROR_KEYS = (("sk-ant-401", "auth"), ("sk-ant-403", "forbidden"), ("sk-ant-429", "rate_limit"),
                        ("sk-ant-529", "overloaded"))
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


def mock_up(port: int, headers: dict[str, str] | None = None) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models", headers=headers or {})
        with urllib.request.urlopen(req, timeout=2) as resp:
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
    probe = ANTHROPIC_PROBE if "--anthropic" in mock_args else None  # the native API needs its key and version
    if not ux.wait_until(lambda: mock_up(mport, probe), 15):
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
    """Clicks the settings dialog's test button, reopening the dialog first when it is closed.
    The dialog animates open and closed: wait for that to settle, then up to four attempts, each with a fresh
    locator and a bounded click."""
    page.wait_for_timeout(700)  # let any open/close animation finish before reading visibility
    last: Exception | None = None
    for _ in range(4):
        try:
            if not page.locator(T("llm-test")).is_visible():
                page.click(T("llm-settings-open"))
                page.wait_for_selector(T("llm-test"), state="visible", timeout=10000)
                page.wait_for_timeout(500)
            page.locator(T("llm-test")).click(timeout=4000)
            return
        except Exception as exc:  # detached, unstable or not yet open: retry with a fresh locator
            last = exc
            page.wait_for_timeout(500)
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
        chats = chat_lines(st)
        plain = bool(chats) and all("browser_header=no" in ln for ln in chats)
        h.check("run: the regular mock log shows browser_header=no for chat requests", plain,
                f"chat lines {len(chats)}, with browser_header=no {sum('browser_header=no' in ln for ln in chats)}")
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
        cors = page.locator('[data-testid="llm-test-result"][data-ok="false"][data-kind="cors"]')
        seen = ux.wait_until(lambda: cors.count() > 0, 25, 0.3)
        h.check("cors: test connection against a mock without CORS headers reports kind=cors (llm-test-result)",
                bool(seen), f"cors error elements {cors.count()}")
        h.shot(page, "cors-error.png")
        # The same failure from a correction run. Reload first, so the settings test result is gone and only the
        # run's error can match; the saved settings survive the reload.
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector(T("llm-open"), timeout=30000)
        open_panel(page)
        run_cors = page.locator('[data-testid="llm-error"][data-kind="cors"]')
        try:
            page.click(T("llm-run"), timeout=10000)
            run_seen = ux.wait_until(lambda: run_cors.count() > 0 and run_cors.first.is_visible(), 30, 0.3)
            run_detail = f"cors error elements {run_cors.count()}"
        except Exception as exc:  # the run could not start: a failed check, not a crash of the group
            run_seen, run_detail = False, f"run not started: {exc!r}"[:200]
        h.check("cors: a correction run shows llm-error[data-kind=cors] too", bool(run_seen), run_detail)
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


# ---- Anthropic emulation (the mock's --anthropic mode) -----------------------------------------------------
def anthropic_override(mport: int) -> str:
    """Init script (test only): the app treats the mock's hosts as Anthropic, via its localStorage override."""
    hosts = f"127.0.0.1:{mport},localhost:{mport}"
    return f"try {{ localStorage.setItem('{ANTHROPIC_HOSTS_KEY}', '{hosts}'); }} catch (e) {{}}"


def choose_provider(page: Any, name: str) -> None:
    """Picks llm-provider-<name>: a RadioGroup item (visible) or a Select item (open llm-provider first)."""
    option = page.locator(T(f"llm-provider-{name}"))
    if not option.is_visible():
        page.click(T("llm-provider"))
        page.wait_for_timeout(200)
    option.click()
    page.wait_for_timeout(300)


def provider_is_anthropic(page: Any) -> bool:
    """Anthropic is in effect: its note shows and the temperature field is disabled."""
    return page.locator(T("llm-anthropic-note")).is_visible() and page.locator(T("llm-temperature")).is_disabled()


def ensure_settings_open(page: Any) -> None:
    if not page.is_visible(T("llm-base-url")):
        open_panel(page)
        page.click(T("llm-settings-open"))
        page.wait_for_selector(T("llm-base-url"), state="visible", timeout=15000)


def save_settings(page: Any) -> None:
    page.click(T("llm-save"))
    page.wait_for_timeout(300)
    if page.is_visible(T("llm-base-url")):  # the dialog stays open after save: close it
        page.keyboard.press("Escape")


def wait_test_result(page: Any, want: dict[str, str], timeout: float = 25) -> dict[str, str]:
    """Polls llm-test-result until its attributes match `want`, so an earlier result never passes for this click."""
    loc = page.locator(T("llm-test-result"))
    last: dict[str, str] = {}

    def matched() -> bool:  # a detached element raises here; ux.wait_until treats that as not yet
        if loc.count() == 0:
            return False
        attrs = loc.first.evaluate("e => Object.fromEntries([...e.attributes].map((a) => [a.name, a.value]))")
        last.clear()
        last.update(attrs)
        return all(attrs.get(k) == v for k, v in want.items())

    ux.wait_until(matched, timeout, 0.3)
    return dict(last)


def mock_log_text(st: Stack) -> str:
    return st.mock_log.read_text(encoding="utf-8") if st.mock_log.exists() else ""


def chat_lines(st: Stack) -> list[str]:
    return [ln for ln in mock_log_text(st).splitlines() if "POST /v1/chat/completions" in ln]


def group_anthropic(h: Any, browser: Any) -> None:
    st = start_stack(h, "anthropic", mock_args=("--anthropic",))
    ctxs: list[Any] = []
    mock_base = f"http://127.0.0.1:{st.mock_port}/v1"
    try:
        ctx, page = h.new_page(browser, extra=anthropic_override(st.mock_port))
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        open_panel(page)
        page.click(T("llm-settings-open"))
        page.wait_for_selector(T("llm-base-url"), state="visible", timeout=15000)
        # Custom first: temperature 0.2 is typed while the field is enabled, so the Anthropic run proves it is omitted.
        choose_provider(page, "custom")
        if page.locator(T("llm-temperature")).is_enabled():
            page.fill(T("llm-temperature"), "0.2")
        else:
            info("anthropic: temperature", "field disabled on Custom; the omission check is not exercised")
        # (a) the preset fills base URL and model and shows the note. The real URL is never test-connected.
        choose_provider(page, "anthropic")
        preset_base = page.input_value(T("llm-base-url"))
        preset_model = page.input_value(T("llm-model"))
        note = page.locator(T("llm-anthropic-note")).is_visible()
        h.check("anthropic: the preset fills base URL and model and shows the note",
                preset_base == ANTHROPIC_BASE and preset_model == ANTHROPIC_MODEL and note,
                f"base {preset_base!r}, model {preset_model!r}, note visible {note}")
        # The mock, typed by hand. The override keeps the provider on Anthropic (b).
        page.fill(T("llm-base-url"), mock_base)
        page.fill(T("llm-api-key"), "sk-ant-test")
        page.fill(T("llm-model"), ANTHROPIC_MODEL)
        h.check("anthropic: the provider still shows Anthropic for the hand-typed mock URL (override)",
                provider_is_anthropic(page), f"base {mock_base}; note visible and temperature disabled")
        save_settings(page)
        # (c)
        click_test(page)
        got = wait_test_result(page, {"data-ok": "true", "data-provider": "anthropic", "data-model-listed": "true"})
        listed = ux.wait_until(lambda: re.search(r"GET /v1/models\b.*browser_header=yes\b.*auth=x-api-key",
                                                  mock_log_text(st)), 10, 0.3)
        h.check("anthropic: test connection ok, provider anthropic, model listed; GET /v1/models has the browser header",
                got.get("data-ok") == "true" and got.get("data-provider") == "anthropic"
                and got.get("data-model-listed") == "true" and bool(listed),
                f"llm-test-result {got}; mock GET line with browser_header=yes auth=x-api-key seen {bool(listed)}")
        # (d) a key whose models list lacks claude-opus-5-5
        ensure_settings_open(page)
        page.fill(T("llm-api-key"), "sk-ant-nomodel")
        save_settings(page)
        click_test(page)
        got2 = wait_test_result(page, {"data-ok": "true", "data-model-listed": "false"})
        h.check("anthropic: key sk-ant-nomodel gives data-ok=true and data-model-listed=false",
                got2.get("data-ok") == "true" and got2.get("data-model-listed") == "false", f"llm-test-result {got2}")
        # (e) the key back, then a run with no uploads
        ensure_settings_open(page)
        page.fill(T("llm-api-key"), "sk-ant-test")
        save_settings(page)
        open_panel(page)
        count = run_correction(page)
        page.wait_for_timeout(300)
        errors = page.locator(T("llm-error")).count()
        h.check("anthropic: a run gets at least 2 llm-diff rows from the fenced prose reply, no llm-error",
                count >= MIN_DIFF_ROWS and errors == 0, f"llm-diff rows {count}, llm-error elements {errors}")
        ok_chat = [ln for ln in chat_lines(st) if "response=valid" in ln and "status=200" in ln]
        wanted = ("browser_header=yes", "temperature=absent", "top_p=absent", "response_format=absent")
        shaped = bool(ok_chat) and all(all(w in ln for w in wanted) for ln in ok_chat)
        h.check("anthropic: chat requests carry browser_header=yes, no temperature, no top_p, no response_format",
                shaped, f"valid chat lines {len(ok_chat)}; first {ok_chat[:1]}")
        maxes = [int(m.group(1)) for m in (re.search(r"max_tokens=(\d+)", ln) for ln in ok_chat) if m]
        h.check("anthropic: chat requests send max_tokens >= 16000", bool(maxes) and min(maxes) >= 16000,
                f"max_tokens on valid chat lines {maxes}")
        h.shot(page, "anthropic-run.png")
        # (f) the same mock in a context without the override: the host is not Anthropic, so the browser sends no
        # header, the preflight gets 400 without Access-Control-Allow-Origin, and the run reports a CORS error.
        ctx3, page3 = h.new_page(browser)
        ctxs.append(ctx3)
        open_run(page3, h.port, st.run_id)
        configure(page3, mock_base, "sk-ant-test", ANTHROPIC_MODEL)
        open_panel(page3)
        cors_run = page3.locator('[data-testid="llm-error"][data-kind="cors"]')
        try:
            page3.click(T("llm-run"), timeout=10000)
            cors_seen = ux.wait_until(lambda: cors_run.count() > 0, 30, 0.3)
            cors_detail = f"llm-error[data-kind=cors] elements {cors_run.count()}"
        except Exception as exc:  # the run could not start: a failed check, not a crash of the group
            cors_seen, cors_detail = False, f"run not started: {exc!r}"[:200]
        preflight_400 = any("OPTIONS" in ln and "browser_header=no" in ln and "status=400" in ln
                            for ln in mock_log_text(st).splitlines())
        h.check("anthropic: without the override the same mock gives llm-error[data-kind=cors]",
                bool(cors_seen), f"{cors_detail}; mock preflight 400 without the header logged {preflight_400}")
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


def group_anthropic_errors(h: Any, browser: Any) -> None:
    st = start_stack(h, "anthropic-errors", mock_args=("--anthropic",))
    ctxs: list[Any] = []
    try:
        ctx, page = h.new_page(browser, extra=anthropic_override(st.mock_port))
        ctxs.append(ctx)
        open_run(page, h.port, st.run_id)
        for key, kind in ANTHROPIC_ERROR_KEYS:
            configure(page, st.base, key, ANTHROPIC_MODEL)
            click_test(page)
            got = wait_test_result(page, {"data-ok": "false", "data-kind": kind})
            h.check(f"anthropic-errors: key {key} gives llm-test-result data-kind={kind}",
                    got.get("data-ok") == "false" and got.get("data-kind") == kind, f"llm-test-result {got}")
            if page.is_visible(T("llm-base-url")):  # close the settings dialog for the next configure
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
    finally:
        for ctx in ctxs:
            ctx.close()
        stop_all(st.viewer, st.mock)


GROUP_FUNCS = {"settings": group_settings, "upload": group_upload, "run": group_run, "review": group_review,
               "export": group_export, "malformed": group_malformed, "cors": group_cors,
               "anthropic": group_anthropic, "anthropic-errors": group_anthropic_errors}


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
