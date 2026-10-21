#!/usr/bin/env python3
"""Reconnect and catch-up checks for noScribe Live, against a server this script starts itself.

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I live/stress/test_reconnect.py [--static DIR] [--port 8767] [--work DIR]
        [--python PY] [--src FEED.ndjson]

It starts `python -m server` on --port with a fresh feeds dir, replays a recorded feed with
`python -m server.replay --speed 0.5 --max-gap 30`, and runs three scenarios in headless Chromium.
Every scenario waits for the page's full UI (and >= 10 rendered segments) before it kills or aborts anything:
the pre-roll shows neither a transcript nor the conn-state chip. Scenarios:

  1. SIGTERM the server mid-run (SIGKILL after 3 s), wait 5 s, restart it on the same port and feeds
     dir. The page must show reconnecting, then live, then catch up to every segment with no duplicates.
  2. A page on the full UI is reloaded with its /api/stream requests aborted for ~6 s (page.route installed
     before the reload), then unrouted, on a second replay. Same reconnecting / live / catch-up checks.
  3. A page opened mid-run (after >= 10 segments are in the feed file) catches up to every segment.

UI contract read from the DOM: [data-testid="conn-state"] with data-state, and each segment's
[data-segment-seq] (fallback [data-segment-index]). Checks that need it are tagged
"[needs UI contract: absent in DOM]" when they fail while the contract is absent from the page.
"machinery" checks read the page's own EventSource (wrapped before the app loads) and the feed file,
so they show whether the server, the replay and the stream work without the contract.

Output: one PASS/FAIL line per check, a SUMMARY line, screenshots in WORK/shots/, server and replay
logs in WORK/logs/. Exit code 0 only if every check passed. Every child process is killed on exit.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent            # live/stress
sys.path.insert(0, str(HERE))                     # run under -I: the script directory is not on sys.path
from test_ux import wait_full_ui  # noqa: E402  (pre-roll wait; same directory)
LIVE_DIR = HERE.parent                            # cwd for `python -m server` and `python -m server.replay`
DEFAULT_STATIC = LIVE_DIR / "web" / "dist"
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_WORK = Path("/tmp/nslive-r2")
RECORDED_FEED = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only
SPEED = "0.5"
MAX_GAP = "30"

# Runs in every document before the app's scripts: counts EventSource opens and errors and records
# every segment/run_end the stream delivers (from `feed` and from `snapshot` catch-ups).
INIT_JS = r"""
(() => {
  if (window.__nsObs) return;
  const O = { opens: 0, errors: 0, feeds: [] };
  window.__nsObs = O;
  const Native = window.EventSource;
  if (!Native) return;
  const note = (events, runId) => {
    for (const ev of events || []) {
      if (ev && ev.type) O.feeds.push({ run_id: runId, type: ev.type, seq: ev.seq });
    }
  };
  const Wrapped = function EventSource(url, init) {
    const es = new Native(url, init);
    es.addEventListener("open", () => { O.opens += 1; });
    es.addEventListener("error", () => { O.errors += 1; });
    es.addEventListener("snapshot", (e) => {
      try { const d = JSON.parse(e.data); note(d.events, d.run_id); } catch (err) {}
    });
    es.addEventListener("feed", (e) => {
      try { const msg = JSON.parse(e.data); note([msg.event], msg.run_id); } catch (err) {}
    });
    return es;
  };
  Wrapped.prototype = Native.prototype;
  Wrapped.CONNECTING = Native.CONNECTING;
  Wrapped.OPEN = Native.OPEN;
  Wrapped.CLOSED = Native.CLOSED;
  window.EventSource = Wrapped;
})();
"""

DOM_JS = r"""() => {
  const all = (sel) => Array.from(document.querySelectorAll(sel));
  const conn = document.querySelector('[data-testid="conn-state"]');
  return {
    seqs: all('[data-segment-seq]').map((e) => e.getAttribute('data-segment-seq')),
    idx: all('[data-segment-index]').map((e) => e.getAttribute('data-segment-index')),
    legacy: all('[role="log"] .segment').length,
    conn: conn ? conn.getAttribute('data-state') : null,
  };
}"""

OBS_JS = "() => window.__nsObs || null"

# Used only when there is no built UI (no index.html): opens a bare EventSource on the stream so the
# machinery (kill, restart, abort, replay, catch-up) can still be checked without the app.
PROBE_JS = """() => {
  if (!window.__nsProbe && window.EventSource) {
    window.__nsProbe = new EventSource('/api/stream?run=latest');
  }
  return !!window.__nsProbe;
}"""


def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_until(fn: Callable[[], Any], timeout: float, step: float = 0.3) -> Any:
    """Call fn until it returns a truthy value or the timeout passes. Returns the last value."""
    end = time.monotonic() + timeout
    while True:
        try:
            value = fn()
        except Exception:  # page navigating, server restarting, feed line half written
            value = None
        if value or time.monotonic() >= end:
            return value
        time.sleep(step)


def feed_info(path: Path) -> dict[str, Any]:
    """Run id, segment count and segment seqs of a feed file. Lines still being written are skipped."""
    run_id = None
    seqs: list[Any] = []
    ended = False
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            run_id = run_id or ev.get("run_id")
            if ev.get("type") == "segment":
                seqs.append(ev.get("seq"))
            elif ev.get("type") == "run_end":
                ended = True
    return {"run_id": run_id, "segments": len(seqs), "seqs": seqs, "ended": ended}


class Lab:
    def __init__(self, args: argparse.Namespace) -> None:
        self.port = args.port
        self.url = f"http://127.0.0.1:{args.port}/"
        self.py = args.python
        self.static = Path(args.static)
        work = Path(args.work)
        self.shots = work / "shots"
        self.logs = work / "logs" / f"reconnect-{time.strftime('%H%M%S')}"
        self.src = Path(args.src) if args.src else work / "src" / RECORDED_FEED.name
        self.feeds = work / "feeds" / f"reconnect-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        for directory in (self.shots, self.logs, self.feeds, self.src.parent):
            directory.mkdir(parents=True, exist_ok=True)
        if args.src is None and not self.src.exists():
            shutil.copyfile(RECORDED_FEED, self.src)
        self.procs: list[subprocess.Popen] = []
        self.results: list[tuple[str, bool, bool]] = []  # (name, ok, failed only because contract absent)
        self.contract_present = False
        self.probe = not (self.static / "index.html").is_file()
        self.server: subprocess.Popen | None = None

    # ---- processes ---------------------------------------------------------------------------------
    @staticmethod
    def _env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep .pyc files out of the worktree
        return env

    def start_server(self, tag: str) -> subprocess.Popen:
        log = open(self.logs / f"server-{tag}.log", "ab")
        cmd = [self.py, "-m", "server", "--port", str(self.port), "--feeds", str(self.feeds),
               "--static", str(self.static)]
        proc = subprocess.Popen(cmd, cwd=LIVE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                env=self._env(), start_new_session=True)
        log.close()
        self.procs.append(proc)
        self.server = proc
        return proc

    def server_up(self, timeout: float = 20.0) -> bool:
        def health() -> bool:
            with urllib.request.urlopen(f"{self.url}api/health", timeout=2) as resp:
                return resp.status == 200
        return bool(wait_until(health, timeout))

    @staticmethod
    def stop_server(proc: subprocess.Popen) -> str:
        if proc.poll() is not None:
            return f"already exited (rc {proc.returncode})"
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
            return f"exited on SIGTERM (rc {proc.returncode})"
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            return "still running after 3 s, SIGKILL"

    def start_replay(self, tag: str) -> subprocess.Popen:
        log = open(self.logs / f"replay-{tag}.log", "ab")
        cmd = [self.py, "-m", "server.replay", str(self.src), "--feeds", str(self.feeds),
               "--speed", SPEED, "--max-gap", MAX_GAP]
        proc = subprocess.Popen(cmd, cwd=LIVE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                env=self._env(), start_new_session=True)
        log.close()
        self.procs.append(proc)
        return proc

    def feeds_now(self) -> set[str]:
        return set(glob.glob(str(self.feeds / "replay-*.ndjson")))

    def new_run(self, before: set[str], tag: str) -> tuple[Path, str]:
        def new_feed() -> Path | None:
            for path in sorted(self.feeds_now() - before):
                return Path(path)
            return None
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

    # ---- page helpers ------------------------------------------------------------------------------
    @staticmethod
    def new_page(browser: Any, label: str) -> tuple[Any, Any]:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(INIT_JS)
        page = ctx.new_page()
        page.on("pageerror", lambda exc: print(f"  page error ({label}): {exc}", flush=True))
        return ctx, page

    def open_page(self, page: Any) -> None:
        page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
        if self.probe:
            page.evaluate(PROBE_JS)

    def counts(self, page: Any, run_id: str | None) -> dict[str, Any]:
        dom = page.evaluate(DOM_JS)
        obs = page.evaluate(OBS_JS) or {"opens": 0, "errors": 0, "feeds": []}
        seqs = dom["seqs"]
        if dom["conn"] is not None or seqs:
            self.contract_present = True
        if seqs:
            rendered = len(seqs)
        elif dom["idx"]:
            rendered = len(dom["idx"])
        else:
            rendered = dom["legacy"]
        feeds = obs["feeds"]
        stream = {str(f.get("seq")) for f in feeds if f.get("type") == "segment" and f.get("run_id") == run_id}
        ended = any(f.get("type") == "run_end" and f.get("run_id") == run_id for f in feeds)
        return {"conn": dom["conn"], "dom": rendered, "dom_seqs": seqs, "stream": stream,
                "ended": ended, "opens": obs["opens"], "errors": obs["errors"]}

    def snap_when(self, page: Any, run_id: str, pred: Callable[[dict[str, Any]], bool],
                  timeout: float) -> dict[str, Any] | None:
        return wait_until(lambda: (lambda c: c if pred(c) else None)(self.counts(page, run_id)),
                          timeout, step=0.5)

    def shot(self, page: Any, name: str) -> None:
        try:
            page.screenshot(path=str(self.shots / name))
        except Exception as exc:
            print(f"  (screenshot {name} failed: {exc})", flush=True)

    # ---- reporting ---------------------------------------------------------------------------------
    def check(self, name: str, ok: bool, detail: str, contract: bool = False) -> None:
        ok = bool(ok)
        absent = contract and not self.contract_present
        note = " [needs UI contract: absent in DOM]" if (not ok and absent) else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}{note}", flush=True)
        self.results.append((name, ok, (not ok) and absent))

    def verify_run(self, tag: str, page: Any, run_id: str, path: Path) -> None:
        info = feed_info(path)
        expected = info["segments"]
        file_seqs = {str(s) for s in info["seqs"]}
        ended = self.snap_when(page, run_id, lambda c: c["ended"], 90)
        self.check(f"{tag} run_end seen by page", ended is not None,
                   f"run {run_id}, feed file has run_end={info['ended']}")
        final = None
        if self.contract_present:
            final = self.snap_when(page, run_id, lambda c: c["dom"] == expected, 25)
        final = final or self.counts(page, run_id)
        self.check(f"{tag} rendered segments == segment lines in feed file", final["dom"] == expected,
                   f"rendered {final['dom']}, feed file {expected} ({path.name})", contract=True)
        seqs = final["dom_seqs"]
        if seqs:
            self.check(f"{tag} no duplicate data-segment-seq", len(seqs) == len(set(seqs)),
                       f"{len(seqs)} attributes, {len(set(seqs))} distinct", contract=True)
            self.check(f"{tag} rendered seqs == feed file seqs", set(seqs) == file_seqs,
                       f"rendered {len(set(seqs))} distinct, feed file {len(file_seqs)}", contract=True)
        else:
            self.check(f"{tag} no duplicate data-segment-seq", False,
                       "no data-segment-seq attributes in the DOM", contract=True)
            self.check(f"{tag} rendered seqs == feed file seqs", False,
                       "no data-segment-seq attributes in the DOM", contract=True)
        self.check(f"{tag} machinery: stream delivered every feed segment", final["stream"] == file_seqs,
                   f"stream distinct {len(final['stream'])}, feed file {len(file_seqs)}")

    # ---- scenarios ---------------------------------------------------------------------------------
    def scenario_restart(self, browser: Any) -> None:
        self.server = self.start_server("a")
        up = self.server_up()
        self.check("setup: server answers /api/health", up, f"python -m server --port {self.port}")
        if not up:
            raise RuntimeError("server did not start; see logs")
        before = self.feeds_now()
        replay = self.start_replay("s1")
        path, run_id = self.new_run(before, "s1")
        ctx, page = self.new_page(browser, "s1")
        self.open_page(page)
        # Kill only once the full UI is up: the pre-roll has no transcript and no conn-state chip to check.
        full = wait_full_ui(page, 90)
        c = self.snap_when(page, run_id, lambda x: x["dom"] >= 10, 60) or self.counts(page, run_id)
        self.check("s1 setup: full UI up and >= 10 segments rendered before the kill", full and c["dom"] >= 10,
                   f"full UI {full}, rendered {c['dom']}, stream distinct {len(c['stream'])}", contract=True)
        errors0, opens0 = c["errors"], c["opens"]
        print(f"  s1: server SIGTERM -> {self.stop_server(self.server)}", flush=True)
        time.sleep(5)
        c = self.counts(page, run_id)
        self.check("s1 reconnecting: conn-state reconnecting 5 s after the server kill",
                   c["conn"] == "reconnecting", f"data-state={c['conn']!r}", contract=True)
        self.shot(page, "s1-reconnecting.png")
        self.check("s1 machinery: page EventSource saw the drop", c["errors"] > errors0,
                   f"EventSource errors {errors0} -> {c['errors']}")
        self.server = self.start_server("b")
        up = self.server_up()
        self.check("s1 restart: server answers on the same port and feeds dir", up,
                   f"port {self.port}, feeds {self.feeds.name}")
        c = self.snap_when(page, run_id, lambda x: x["conn"] == "live", 40) or self.counts(page, run_id)
        self.check("s1 live: conn-state live after the restart", c["conn"] == "live",
                   f"data-state={c['conn']!r}", contract=True)
        self.shot(page, "s1-live.png")
        self.check("s1 machinery: page EventSource reopened", c["opens"] > opens0,
                   f"EventSource opens {opens0} -> {c['opens']}")
        replay.wait(timeout=300)
        self.verify_run("s1", page, run_id, path)
        self.shot(page, "s1-run_end.png")
        ctx.close()

    def scenario_abort(self, browser: Any) -> None:
        before = self.feeds_now()
        replay = self.start_replay("s2")
        path, run_id = self.new_run(before, "s2")
        ctx, page = self.new_page(browser, "s2")

        def is_stream(url: Any) -> bool:
            return "/api/stream" in str(url)

        def abort(route: Any) -> None:
            route.abort()

        # Abort only once the page is on the full UI with >= 10 segments rendered. The route is then installed and
        # the page reloaded, so the reloaded page's first /api/stream request is aborted.
        self.open_page(page)
        full = wait_full_ui(page, 90)
        c = self.snap_when(page, run_id, lambda x: x["dom"] >= 10, 60) or self.counts(page, run_id)
        self.check("s2 setup: full UI up and >= 10 segments rendered before the abort", full and c["dom"] >= 10,
                   f"full UI {full}, rendered {c['dom']}, stream distinct {len(c['stream'])}", contract=True)
        page.route(is_stream, abort)
        self.open_page(page)
        seen: set[Any] = set()
        last: dict[str, Any] = {"errors": 0, "opens": 0}
        end = time.monotonic() + 6.0
        while time.monotonic() < end:
            try:
                last = self.counts(page, run_id)
                seen.add(last["conn"])
            except Exception:
                pass
            time.sleep(0.5)
        self.check("s2 outage: conn-state reconnecting while /api/stream is aborted",
                   "reconnecting" in seen, f"data-state values seen over 6 s: {sorted(str(x) for x in seen)}",
                   contract=True)
        self.check("s2 machinery: aborted stream produces EventSource errors", last["errors"] > 0,
                   f"EventSource errors {last['errors']}, opens {last['opens']}")
        self.shot(page, "s2-outage.png")
        page.unroute(is_stream, abort)
        wait_full_ui(page, 60)  # the pre-roll hides the conn-state chip until the full UI is up
        c = self.snap_when(page, run_id, lambda x: x["conn"] == "live", 40) or self.counts(page, run_id)
        self.check("s2 live: conn-state live after unroute", c["conn"] == "live",
                   f"data-state={c['conn']!r}", contract=True)
        replay.wait(timeout=300)
        self.verify_run("s2", page, run_id, path)
        self.shot(page, "s2-run_end.png")
        ctx.close()

    def scenario_join(self, browser: Any) -> None:
        before = self.feeds_now()
        replay = self.start_replay("s3")
        path, run_id = self.new_run(before, "s3")
        wait_until(lambda: feed_info(path)["segments"] >= 10, 60)
        at_open = feed_info(path)
        ctx, page = self.new_page(browser, "s3")
        self.open_page(page)
        self.check("s3 setup: page opened mid-run (>= 10 segments in the feed)",
                   at_open["segments"] >= 10 and not at_open["ended"],
                   f"feed had {at_open['segments']} segments, run_end={at_open['ended']} at open")
        replay.wait(timeout=300)
        wait_full_ui(page, 60)  # the DOM counts need the full UI (the pre-roll has no segments in the DOM)
        self.verify_run("s3", page, run_id, path)
        self.shot(page, "s3-run_end.png")
        ctx.close()

    def run_all(self, browser: Any) -> None:
        for name, fn in (("scenario 1", self.scenario_restart), ("scenario 2", self.scenario_abort),
                         ("scenario 3", self.scenario_join)):
            try:
                fn(browser)
            except Exception as exc:
                self.check(f"{name} completed", False, f"crashed: {exc!r}")

    def summary(self) -> bool:
        passed = [r for r in self.results if r[1]]
        failed = [r for r in self.results if not r[1]]
        absent = [r for r in failed if r[2]]
        print(f"SUMMARY: {len(passed)}/{len(self.results)} checks passed; {len(failed)} failed, "
              f"{len(absent)} of them only because the UI contract is absent", flush=True)
        for name, _ok, only_contract in failed:
            print(f"  failed: {name}{' (contract absent)' if only_contract else ''}", flush=True)
        print(f"  screenshots: {self.shots}", flush=True)
        print(f"  logs: {self.logs}", flush=True)
        return not failed


def _exit_on_term(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # unwinds through `finally`, so child processes are killed


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _exit_on_term)
    parser = argparse.ArgumentParser(description="Reconnect and catch-up checks for noScribe Live.")
    parser.add_argument("--static", default=str(DEFAULT_STATIC), help="built frontend dir (has index.html)")
    parser.add_argument("--port", type=int, default=8767, help="port for the server this script starts")
    parser.add_argument("--python", default=DEFAULT_PY, help="python with the server deps (default: live venv)")
    parser.add_argument("--work", default=str(DEFAULT_WORK), help="scratch dir for feeds, shots, logs")
    parser.add_argument("--src", default=None, help="recorded feed to replay (default: copy of the demo feed)")
    args = parser.parse_args(argv)

    if port_busy(args.port):
        print(f"FAIL setup: port {args.port} is already in use; not touching that process")
        return 2
    if not (Path(args.static) / "index.html").is_file():
        print(f"NOTE: {args.static}/index.html is missing; the server serves its placeholder page, "
              "so every UI check will fail", flush=True)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    lab = Lab(args)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                lab.run_all(browser)
            finally:
                browser.close()
    finally:
        lab.cleanup()
    return 0 if lab.summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())
