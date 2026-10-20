#!/usr/bin/env python3
"""Follow-mode checks for noScribe Live, against a server this script starts itself.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I live/stress/test_follow.py [--static DIR] [--port 8769] [--work DIR] [--python PY]

It starts `python -m server` on --port with a fresh feeds dir and replays the recorded demo feed twice:
replay A (`--speed 0.5`, long, stays live) and replay B (`--speed 6 --max-gap 1`, short). Scenarios:

  1. The page is opened in follow mode while A runs; B starts 4 s later. The page must show B while B
     runs (run-state running), and follow A again after B's run_end (the server's run=latest prefers live runs).
  2. B is picked explicitly in the run picker (finished): run-state reads "finished", not "Live"; the
     other-live-run button offers A; the page stays on B for 6 s; clicking the button shows A running.
  3. Replay A is SIGKILLed: the server reports the run stale (data-state="stale", timeout 20 s); the
     Elapsed tile must read the same value 4 s apart.

Which run the page shows is read from the stream: the run_id of the newest event the page received.
Both replays carry the same audio name, so the run picker cannot tell them apart by name; it is used
only through the status word ("Finished" = B, "Running" = A). Helpers and the EventSource observer
(INIT_JS) come from test_reconnect.py.

Output: one PASS/FAIL line per check, a SUMMARY line, screenshots in WORK/shots/, server and replay logs
in WORK/logs/. Exit code 0 only if every check passed. Every child process is killed on exit.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # live/stress
sys.path.insert(0, str(HERE))                     # reuse test_reconnect helpers, also under `python -I`
from test_reconnect import INIT_JS, feed_info, port_busy, wait_until  # noqa: E402

LIVE_DIR = HERE.parent                            # cwd for `python -m server` and `python -m server.replay`
DEFAULT_STATIC = LIVE_DIR / "web" / "dist"
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_WORK = Path("/tmp/nslive-r2/follow")
RECORDED_FEED = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only

FEED_JS = "() => (window.__nsObs ? window.__nsObs.feeds : [])"
RUN_STATE_JS = """() => {
  const el = document.querySelector('[data-testid="run-state"]');
  return el ? { state: el.getAttribute('data-state'), text: el.textContent.trim() } : null;
}"""
# The Elapsed chip: the element whose own text is "Elapsed", then the value next to it.
ELAPSED_JS = r"""() => {
  const label = [...document.querySelectorAll('body *')]
    .find((el) => el.childElementCount === 0 && el.textContent.trim() === 'Elapsed');
  if (!label) return null;
  let node = label.parentElement;
  while (node && node.textContent.replace('Elapsed', '').trim() === '') node = node.parentElement;
  return node ? node.textContent.replace('Elapsed', '').trim() : null;
}"""


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # unwinds through `finally`, so child processes are killed


def new_page(browser: Any) -> tuple[Any, Any]:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(INIT_JS)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: print(f"  page error: {exc}", flush=True))
    return ctx, page


# ---- page reads -----------------------------------------------------------------------------------
def feed_of(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(FEED_JS) or []


def shown_run(page: Any) -> str | None:
    """Run id of the newest event the page received, i.e. the run it is showing."""
    feeds = feed_of(page)
    return feeds[-1].get("run_id") if feeds else None


def count_run(page: Any, run_id: str) -> int:
    return sum(1 for e in feed_of(page) if e.get("run_id") == run_id)


def ended(page: Any, run_id: str) -> bool:
    return any(e.get("run_id") == run_id and e.get("type") == "run_end" for e in feed_of(page))


def run_info(page: Any) -> dict[str, Any]:
    return page.evaluate(RUN_STATE_JS) or {}


def state(page: Any) -> str | None:
    return run_info(page).get("state")


def elapsed(page: Any) -> str | None:
    return page.evaluate(ELAPSED_JS)


def pick(page: Any, status_word: str) -> None:
    """Open the run picker and choose the entry whose status word matches (Running / Finished)."""
    page.get_by_role("combobox", name="Choose a run").click()
    page.get_by_role("option", name=re.compile(status_word)).first.click()


class Lab:
    def __init__(self, args: argparse.Namespace) -> None:
        self.port = args.port
        self.url = f"http://127.0.0.1:{args.port}/"
        self.py = args.python
        self.static = Path(args.static)
        work = Path(args.work)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.shots = work / "shots"
        self.logs = work / "logs" / f"follow-{stamp}"
        self.src = work / "src" / RECORDED_FEED.name
        self.feeds = work / "feeds" / f"follow-{stamp}-{os.getpid()}"
        for directory in (self.shots, self.logs, self.feeds, self.src.parent):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.src.exists():
            shutil.copyfile(RECORDED_FEED, self.src)
        self.procs: list[subprocess.Popen] = []
        self.results: list[tuple[str, bool]] = []

    # ---- processes ---------------------------------------------------------------------------------
    @staticmethod
    def _env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep .pyc files out of the worktree
        return env

    def _spawn(self, cmd: list[str], log_name: str) -> subprocess.Popen:
        with open(self.logs / log_name, "ab") as log:
            proc = subprocess.Popen(cmd, cwd=LIVE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                    env=self._env(), start_new_session=True)
        self.procs.append(proc)
        return proc

    def start_server(self) -> subprocess.Popen:
        cmd = [self.py, "-m", "server", "--port", str(self.port), "--feeds", str(self.feeds),
               "--static", str(self.static)]
        return self._spawn(cmd, "server.log")

    def server_up(self) -> bool:
        def health() -> bool:
            with urllib.request.urlopen(f"{self.url}api/health", timeout=2) as resp:
                return resp.status == 200
        return bool(wait_until(health, 20))

    def start_replay(self, speed: float, max_gap: float, tag: str) -> subprocess.Popen:
        cmd = [self.py, "-m", "server.replay", str(self.src), "--feeds", str(self.feeds),
               "--speed", str(speed), "--max-gap", str(max_gap)]
        return self._spawn(cmd, f"replay-{tag}.log")

    def feeds_now(self) -> set[str]:
        return set(glob.glob(str(self.feeds / "replay-*.ndjson")))

    def new_run(self, before: set[str], tag: str) -> tuple[Path, str]:
        def new_feed() -> Path | None:
            fresh = sorted(self.feeds_now() - before)
            return Path(fresh[0]) if fresh else None
        path = wait_until(new_feed, 15)
        if not path:
            raise RuntimeError(f"{tag}: replay did not create a feed file in {self.feeds}")
        run_id = wait_until(lambda: feed_info(path)["run_id"], 15)
        if not run_id:
            raise RuntimeError(f"{tag}: feed file {path.name} has no run_start yet")
        return path, run_id

    def cleanup(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    # ---- reporting ---------------------------------------------------------------------------------
    def check(self, name: str, ok: bool, detail: str) -> None:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
        self.results.append((name, bool(ok)))

    def shot(self, page: Any, name: str) -> None:
        try:
            page.screenshot(path=str(self.shots / name))
        except Exception as exc:
            print(f"  (screenshot {name} failed: {exc})", flush=True)

    def summary(self) -> bool:
        failed = [name for name, ok in self.results if not ok]
        print(f"SUMMARY: {len(self.results) - len(failed)}/{len(self.results)} checks passed; "
              f"{len(failed)} failed", flush=True)
        for name in failed:
            print(f"  failed: {name}", flush=True)
        print(f"  screenshots: {self.shots}", flush=True)
        print(f"  logs: {self.logs}", flush=True)
        return not failed


def run_checks(lab: Lab, browser: Any) -> None:
    # ---- scenario 1: follow newest, live runs preferred ------------------------------------------
    before = lab.feeds_now()
    replay_a = lab.start_replay(0.5, 2, "A")
    _path_a, run_a = lab.new_run(before, "A")
    ctx, page = new_page(browser)
    page.goto(lab.url, wait_until="domcontentloaded", timeout=30000)
    on_a = wait_until(lambda: shown_run(page) == run_a and state(page) == "running", 15)
    lab.check("setup: follow page shows A (run-state running) before B starts", bool(on_a),
              f"run-state {run_info(page)}")
    time.sleep(4)  # B starts 4 s after A

    before_b = lab.feeds_now()
    replay_b = lab.start_replay(6, 1, "B")
    path_b, run_b = lab.new_run(before_b, "B")
    on_b = wait_until(lambda: shown_run(page) == run_b and state(page) == "running", 15)
    lab.check("1 follow newest: page shows B while B runs", bool(on_b),
              f"shown run is B={shown_run(page) == run_b}, run-state {run_info(page)}")
    lab.shot(page, "01-follow-b-running.png")

    wait_until(lambda: ended(page, run_b), 40)
    t_end = time.monotonic()
    back = wait_until(lambda: shown_run(page) == run_a, 15)
    delay = time.monotonic() - t_end
    lab.check("1 follow newest: page follows A again after B's run_end",
              bool(back) and state(page) == "running",
              f"B run_end seen={ended(page, run_b)}; switched to A after {delay:.1f} s "
              f"(spec: ~5 s); run-state {run_info(page)}")
    lab.shot(page, "02-follow-a-after-b.png")
    replay_b.wait(timeout=60)

    # ---- scenario 2: explicit pick is never yanked; switch button -------------------------------
    pick(page, "Finished")
    wait_until(lambda: state(page) == "finished", 10)
    info = run_info(page)
    lab.check("2 explicit pick: run-state finished, not Live",
              info.get("state") == "finished" and info.get("text") != "Live", f"run-state {info}")
    other = page.locator('[data-testid="other-live-run"]')
    offered = wait_until(lambda: other.is_visible(), 5)
    lab.check("2 other-live-run button offers the running run", bool(offered),
              f"button text {other.inner_text() if offered else None!r}")
    seen_a = count_run(page, run_a)
    time.sleep(6)
    still_b = shown_run(page) == run_b and count_run(page, run_a) == seen_a and state(page) == "finished"
    lab.check("2 explicit pick is never yanked: still on B after 6 s", still_b,
              f"A events received {seen_a} -> {count_run(page, run_a)}, run-state {run_info(page)}")
    lab.shot(page, "03-explicit-b-finished.png")
    other.click()
    switched = wait_until(lambda: shown_run(page) == run_a and state(page) == "running", 10)
    lab.check("2 switch button: page now shows A with run-state running", bool(switched),
              f"shown run is A={shown_run(page) == run_a}, run-state {run_info(page)}, "
              f"button visible now={other.is_visible()}")
    lab.shot(page, "04-switched-to-a.png")

    # ---- scenario 3: a killed run's Elapsed stops -----------------------------------------------
    e0 = elapsed(page)
    time.sleep(2)
    e1 = elapsed(page)
    lab.check("3 setup: Elapsed ticks while A runs", e0 is not None and e0 != e1 and state(page) == "running",
              f"{e0!r} -> {e1!r} over 2 s, run-state {state(page)!r}")
    os.kill(replay_a.pid, signal.SIGKILL)
    replay_a.wait(timeout=10)
    stale = wait_until(lambda: state(page) == "stale", 20, step=0.3)
    lab.check("3 killed run: run-state stale within 20 s", bool(stale), f"run-state {run_info(page)}")
    lab.shot(page, "05-stale.png")
    x1 = elapsed(page)
    time.sleep(4)
    x2 = elapsed(page)
    lab.check("3 elapsed frozen for the killed run", x1 is not None and x1 == x2 and ":" in x1,
              f"Elapsed {x1!r} then {x2!r} 4 s later")
    lab.shot(page, "06-stale-elapsed.png")
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _exit_on_term)
    parser = argparse.ArgumentParser(description="Follow-mode checks for noScribe Live.")
    parser.add_argument("--static", default=str(DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--port", type=int, default=8769, help="port for the server this script starts")
    parser.add_argument("--python", default=DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs")
    args = parser.parse_args(argv)

    if port_busy(args.port):
        print(f"FAIL setup: port {args.port} is already in use; not touching that process", flush=True)
        return 2
    if not (Path(args.static) / "index.html").is_file():
        print(f"NOTE: {args.static}/index.html is missing; the UI checks will fail", flush=True)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    lab = Lab(args)
    try:
        lab.start_server()
        up = lab.server_up()
        lab.check("setup: server answers /api/health", up, f"python -m server --port {lab.port}")
        if up:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    try:
                        run_checks(lab, browser)
                    except Exception as exc:
                        lab.check("scenarios completed", False, f"crashed: {exc!r}")
                finally:
                    browser.close()
    finally:
        lab.cleanup()
    return 0 if lab.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
