#!/usr/bin/env python3
"""Follow-mode checks for noScribe Live, against a server this script starts itself.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I live/stress/test_follow.py [--static DIR] [--port 8769] [--work DIR] [--python PY]

It starts `python -m server` on --port with a fresh feeds dir and replays the recorded demo feed twice:
replay A (`--speed 0.2 --max-gap 5`, about 94 s, so it is still live through scenarios 1 and 2; scenario 3
kills it) and replay B (`--speed 1 --max-gap 30`, about 50 s). Scenarios:

  1. The page is opened in follow mode while A runs; B starts 4 s later. The page must show B while B
     runs (run-state running), and follow A again after B's run_end (the server's run=latest prefers live runs).
  2. B is picked explicitly in the run picker (finished): run-state reads "finished", not "Live"; the
     other-live-run button offers A; the page stays on B for 6 s; clicking the button shows A running.
     A and B share one audio name, so the picker option must show B's start time to the second (HH:MM:SS).
  3. Replay A is SIGKILLed: the server reports the run stale (data-state="stale", timeout 20 s); the stage
     card says it stopped and run-state is not Live; the Elapsed tile must read the same value 4 s apart.

Which run the page shows is read from the stream: the run_id of the newest event the page received.
Helpers and the EventSource observer (INIT_JS) come from test_reconnect.py. DIAG_JS also records the stream
URLs the page opens and the runs list of each hello; scenario 2 prints them as DIAG lines.

Output: one PASS/FAIL line per check, a SUMMARY line, screenshots in WORK/shots/, server and replay logs
in WORK/logs/. Exit code 0 only if every check passed. Every child process is killed on exit.
"""

from __future__ import annotations

import argparse
import glob
import json
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
from test_ux import wait_full_ui  # noqa: E402  (pre-roll wait; same directory)

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
# Runs in every document after INIT_JS: records each /api/stream URL the page opens and the runs list
# of every hello (run_id, status, live), so a failed check can show which run the page asked for.
DIAG_JS = r"""
(() => {
  if (window.__nsDiag) return;
  const D = { streams: [], hellos: [] };
  window.__nsDiag = D;
  const Prev = window.EventSource;
  if (!Prev) return;
  const Wrapped = function EventSource(url, init) {
    const link = String(url);
    D.streams.push(link);
    const es = new Prev(url, init);
    es.addEventListener("hello", (e) => {
      try {
        const d = JSON.parse(e.data);
        D.hellos.push({
          url: link,
          runs: (d.runs || []).map((r) => ({ run_id: r.run_id, status: r.status, live: r.live, started_t: r.started_t })),
        });
      } catch (err) {}
    });
    return es;
  };
  Wrapped.prototype = Prev.prototype;
  Wrapped.CONNECTING = Prev.CONNECTING;
  Wrapped.OPEN = Prev.OPEN;
  Wrapped.CLOSED = Prev.CLOSED;
  window.EventSource = Wrapped;
})();
"""


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # unwinds through `finally`, so child processes are killed


def new_page(browser: Any) -> tuple[Any, Any]:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(INIT_JS)
    ctx.add_init_script(DIAG_JS)
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


# A run on the air reads "● Live" (green) or, before its first segment, "◐ Loading" (yellow); both carry
# data-state running. The glyph is part of the chip text (top-bar.tsx), so the check matches it too.
RUNNING_CHIP = re.compile(r"^(●\s*(Live|即時)|◐\s*(Loading|載入中))$")


def running(page: Any) -> bool:
    """True while a run is on the air: data-state running, chip Live/即時 or Loading/載入中 with its glyph."""
    info = run_info(page)
    return info.get("state") == "running" and bool(RUNNING_CHIP.match(info.get("text") or ""))


def elapsed(page: Any) -> str | None:
    return page.evaluate(ELAPSED_JS)


def pick(page: Any, run_id: str) -> str:
    """Open the run picker (Popover trigger), choose the option whose data-run-id is run_id; return its text."""
    page.locator('[data-testid="run-picker"]').click(timeout=5000)
    option = page.locator(f'[data-testid="run-option"][data-run-id="{run_id}"]')
    option.wait_for(state="visible", timeout=5000)
    text = option.inner_text()
    option.click(timeout=5000)
    return text


def diagnostics(lab: Lab, page: Any) -> dict[str, Any]:
    return {
        "streams_opened": page.evaluate("() => (window.__nsDiag ? window.__nsDiag.streams : [])"),
        "last_hello": page.evaluate(
            "() => { const d = window.__nsDiag; return d && d.hellos.length ? d.hellos[d.hellos.length - 1] : null; }"
        ),
        "other_live_buttons_in_dom": page.locator('[data-testid="other-live-run"]').count(),
        "header_text": page.evaluate(
            r"() => { const h = document.querySelector('header'); return h ? h.innerText.replace(/\n+/g, ' | ') : null; }"
        ),
        "server_api_runs": lab.api_runs(),
    }


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

    def api_runs(self) -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(f"{self.url}api/runs", timeout=3) as resp:
                data = json.load(resp)
        except Exception as exc:  # report, do not crash the scenario
            return [{"error": repr(exc)}]
        runs = data.get("runs", []) if isinstance(data, dict) else data
        return [{k: r.get(k) for k in ("run_id", "status", "live", "started_t", "audio_name")}
                for r in runs if isinstance(r, dict)]

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


def scenario_2(lab: Lab, page: Any, path_a: Path, run_a: str, run_b: str) -> None:
    a_feed = path_a.read_text(encoding="utf-8")
    lab.check("2 setup: run A still running (no run_end in its feed) when B is picked",
              "run_end" not in a_feed, f"feed {path_a.name}")
    started_b = next((r.get("started_t") for r in lab.api_runs() if r.get("run_id") == run_b), None)
    expected = time.strftime("%H:%M:%S", time.localtime(started_b)) if started_b else "?"
    text = pick(page, run_b)
    wait_until(lambda: state(page) == "finished" and shown_run(page) == run_b, 10)
    info = run_info(page)
    on_b = shown_run(page) == run_b
    lab.check("2 picker: the finished option is B and shows its start time HH:MM:SS",
              expected in text and "Finished" in text,
              f"option text {text!r}, expected start time {expected}")
    lab.check("2 explicit pick: shows B, run-state finished, not Live",
              on_b and info.get("state") == "finished" and info.get("text") != "Live",
              f"shown run is B={on_b}, run-state {info}")

    other = page.locator('[data-testid="other-live-run"]')
    offered = wait_until(lambda: other.is_visible(), 5)
    print(f"  DIAG after explicit pick: {json.dumps(diagnostics(lab, page), ensure_ascii=False)}", flush=True)
    lab.check("2 other-live-run button offers the running run", bool(offered),
              f"button text {other.inner_text() if offered else None!r}")

    seen_a = count_run(page, run_a)
    time.sleep(6)
    still_b = shown_run(page) == run_b and count_run(page, run_a) == seen_a and state(page) == "finished"
    lab.check("2 explicit pick is never yanked: still on B after 6 s", still_b,
              f"A events received {seen_a} -> {count_run(page, run_a)}, run-state {run_info(page)}")
    lab.shot(page, "03-explicit-b-finished.png")

    if offered:
        other.click(timeout=5000)
    wait_until(lambda: shown_run(page) == run_a, 10)
    switched = wait_full_ui(page, 30) and bool(wait_until(lambda: running(page), 5))
    lab.check("2 switch button: page now shows A with run-state running", bool(offered) and bool(switched),
              f"button offered={bool(offered)}, shown run is A={shown_run(page) == run_a}, "
              f"run-state {run_info(page)}, button visible now={other.is_visible()}")
    lab.shot(page, "04-switched-to-a.png")


def scenario_3(lab: Lab, page: Any, replay_a: subprocess.Popen, path_a: Path) -> None:
    # Kill A as soon as the full UI is up and Elapsed has ticked: no waiting for more events, so the replay
    # must still be running at that point (checked against A's feed file).
    wait_full_ui(page, 30)
    e0 = elapsed(page)
    ticked = wait_until(lambda: e0 is not None and elapsed(page) not in (None, e0) and running(page),
                        5, 0.1)
    e1 = elapsed(page)
    still_live = "run_end" not in path_a.read_text(encoding="utf-8")
    lab.check("3 setup: Elapsed ticks while A runs and A has no run_end yet (killed while live)",
              bool(ticked) and still_live and running(page),
              f"{e0!r} -> {e1!r}, run-state {state(page)!r}, run_end absent from A's feed={still_live}")
    os.kill(replay_a.pid, signal.SIGKILL)
    replay_a.wait(timeout=10)
    stale = wait_until(lambda: state(page) == "stale", 20, step=0.3)
    info = run_info(page)
    lab.check("3 killed run: run-state stale within 20 s", bool(stale), f"run-state {info}")
    stopped = page.evaluate(
        "() => document.body.innerText.includes('轉錄意外中止') || document.body.innerText.includes('Stopped unexpectedly')"
    )
    lab.check("3 killed run: stage card shows the stopped end state; run-state is not Live",
              bool(stale) and bool(stopped) and info.get("text") != "Live",
              f"stopped text on page={bool(stopped)}, run-state {info}")
    lab.shot(page, "05-stale.png")
    x1 = elapsed(page)
    time.sleep(4)
    x2 = elapsed(page)
    lab.check("3 elapsed frozen for the killed run", x1 is not None and x1 == x2 and ":" in x1,
              f"Elapsed {x1!r} then {x2!r} 4 s later")
    lab.shot(page, "06-stale-elapsed.png")


def run_checks(lab: Lab, browser: Any) -> None:
    # ---- scenario 1: follow newest, live runs preferred ------------------------------------------
    before = lab.feeds_now()
    # Replay A is paced by gap / speed, capped at max-gap: speed 0.2 with cap 30 is never shorter than the old
    # cap of 5, and it stays live through the pre-roll, B's run and scenario 2 so that scenario 3 can kill it.
    replay_a = lab.start_replay(0.2, 30, "A")
    path_a, run_a = lab.new_run(before, "A")
    ctx, page = new_page(browser)
    page.goto(lab.url, wait_until="domcontentloaded", timeout=30000)
    wait_until(lambda: shown_run(page) == run_a, 15)
    on_a = wait_full_ui(page, 30) and bool(wait_until(lambda: running(page), 5))
    lab.check("setup: follow page shows A (run-state running) before B starts", bool(on_a),
              f"run-state {run_info(page)}")
    time.sleep(4)  # B starts 4 s after A

    before_b = lab.feeds_now()
    replay_b = lab.start_replay(1, 30, "B")
    path_b, run_b = lab.new_run(before_b, "B")
    wait_until(lambda: shown_run(page) == run_b, 15)
    on_b = wait_full_ui(page, 30) and bool(wait_until(lambda: running(page), 5))
    lab.check("1 follow newest: page shows B while B runs", bool(on_b),
              f"shown run is B={shown_run(page) == run_b}, run-state {run_info(page)}")
    lab.shot(page, "01-follow-b-running.png")

    # The server switches to A as soon as B ends and sends A's snapshot instead of B's run_end, so the
    # page need not receive B's run_end. Time the switch from B's feed file, not from the page's feed.
    ended_b = wait_until(lambda: "run_end" in path_b.read_text(encoding="utf-8"), 90)
    t_end = time.monotonic()
    back = wait_until(lambda: shown_run(page) == run_a, 15)
    delay = time.monotonic() - t_end
    # The run-state chip is hidden during the pre-roll of the switched-to run: read it only after the full UI.
    full_a = wait_full_ui(page, 30)
    running_a = bool(wait_until(lambda: running(page), 5)) if full_a else False
    lab.check("1 follow newest: page follows A again after B's run_end",
              bool(ended_b) and bool(back) and full_a and running_a,
              f"B run_end in its feed={bool(ended_b)}, seen by page={ended(page, run_b)}; "
              f"switched to A {delay:.1f} s after it (spec: ~5 s); full UI {full_a}, run-state {run_info(page)}")
    lab.shot(page, "02-follow-a-after-b.png")
    replay_b.wait(timeout=60)

    # ---- scenarios 2 and 3: each one runs even if the other crashes -----------------------------
    try:
        scenario_2(lab, page, path_a, run_a, run_b)
    except Exception as exc:
        lab.check("2 scenario completed", False, f"crashed: {exc!r}")
    try:
        scenario_3(lab, page, replay_a, path_a)
    except Exception as exc:
        lab.check("3 scenario completed", False, f"crashed: {exc!r}")
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
