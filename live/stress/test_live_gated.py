#!/usr/bin/env python3
"""Item 9 (gated viewer): the :8766 server is killed and restarted while a replay runs, and the page recovers.

Run by the lead after the final deploy, against the live gated viewer. It reads the token from
/workspace/noScribe-live/live/logs/.token and the public URL from logs/tunnel-url.txt, starts a replay of the
demo feed INTO /workspace/noScribe-live/live/feeds (speed 1, --max-gap 3), opens Chromium at URL?token=...,
waits for 8 rendered segments, kills the :8766 server (pid from logs/viewer-gated.pid: SIGTERM, SIGKILL after
3 s), waits 6 s and asserts conn-state reconnecting plus the banner, restarts the server with the same command
line as the deploy, waits for conn-state live, and at the replay's run_end asserts that the rendered segments
equal the feed's segments with no duplicate data-segment-seq. A :8766 server is always left running at exit.

    /usr/bin/python3 -I live/stress/test_live_gated.py

Reuses the DOM readers and the feed helpers of test_ux.py (same directory). Not run by the r7 author; the lead runs it.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # live/stress
sys.path.insert(0, str(HERE))
import test_ux as ux  # noqa: E402  (DOM readers, wait_until, feed_info, port_busy; same directory)

LIVE = Path("/workspace/noScribe-live/live")
TOKEN_FILE = LIVE / "logs" / ".token"
URL_FILE = LIVE / "logs" / "tunnel-url.txt"
PID_FILE = LIVE / "logs" / "viewer-gated.pid"
FEEDS = LIVE / "feeds"
VENV_PY = LIVE / ".venv" / "bin" / "python"
DEMO = FEEDS / ux.DEMO_NAME                         # 50 segments, read as the replay source
PORT = 8766
DEFAULT_URL = "http://bore.pub:30138"
RESTART_TEMPLATE = ("cd /workspace/noScribe-live/live && LIVE_TOKEN={token} setsid nohup .venv/bin/python "
                    "-m server --port 8766 >> logs/viewer-gated.log 2>&1 &")

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str) -> None:
    ok = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    results.append((name, ok))


def viewer_pids() -> list[int]:
    """Pids of `python -m server --port 8766` run from the live directory (read from /proc, nothing else)."""
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = [a.decode(errors="replace") for a in (entry / "cmdline").read_bytes().split(b"\0") if a]
            cwd = os.readlink(entry / "cwd")
        except OSError:
            continue
        if not args or "python" not in args[0]:
            continue
        if " -m server --port 8766" in " ".join(args) and cwd == str(LIVE):
            found.append(int(entry.name))
    return sorted(found)


def restart_viewer(token: str) -> int | None:
    """Starts the gated viewer with the deploy command line; records its pid in logs/viewer-gated.pid."""
    subprocess.run(["bash", "-c", RESTART_TEMPLATE.format(token=token)], stdin=subprocess.DEVNULL, check=False)
    pid = ux.wait_until(lambda: (viewer_pids() or [None])[-1], 20, 0.5)
    if pid:
        PID_FILE.write_text(f"{pid}\n", encoding="utf-8")
    return pid or None


def kill_viewer(pid: int) -> None:
    """SIGTERM, then SIGKILL after 3 s if the process is still alive."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + 3
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def replay_feeds() -> set[str]:
    return {str(p) for p in FEEDS.glob("replay-*.ndjson")}


def run_scenario(token: str, url: str, replay_box: list[subprocess.Popen]) -> None:
    env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = replay_feeds()
    Path("/tmp/nslive-r7").mkdir(parents=True, exist_ok=True)
    log = open("/tmp/nslive-r7/replay-gated-r7.log", "ab")          # scratch log; nothing new in the live tree
    replay = subprocess.Popen([str(VENV_PY), "-m", "server.replay", str(DEMO), "--feeds", str(FEEDS),
                               "--speed", "1", "--max-gap", "3"],
                              cwd=LIVE, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    replay_box.append(replay)
    fresh = ux.wait_until(lambda: sorted(replay_feeds() - before) or None, 20, 0.3)
    if not fresh:
        check("replay started into live/feeds", False, "no replay-*.ndjson appeared")
        return
    path = FEEDS / fresh[0].rsplit("/", 1)[-1]
    rid = ux.wait_until(lambda: ux.feed_info(path)["run_id"], 15, 0.3)
    check("replay started into live/feeds", bool(rid), f"feed {path.name}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(viewport=ux.VIEWPORT)
            ctx.add_init_script(ux.INIT_JS)
            page = ctx.new_page()
            page.goto(f"{url}?token={urllib.parse.quote(token)}", wait_until="domcontentloaded", timeout=60000)
            rendered = ux.wait_until(lambda: ux.seg_count(page) >= 8, 120, 0.5) or 0
            check("before the kill: at least 8 segments rendered", ux.seg_count(page) >= 8,
                  f"{ux.seg_count(page)} rendered")
            old = ux.wait_until(lambda: (viewer_pids() or [None])[-1], 5, 0.3)
            pid_text = PID_FILE.read_text(encoding="utf-8").strip() if PID_FILE.exists() else ""
            # kill only a pid that /proc confirms is the gated viewer (a stale pid file must not hit another process)
            pid = int(pid_text) if pid_text.isdigit() and int(pid_text) in viewer_pids() else old
            if not pid:
                check("kill the :8766 server", False, "no pid in logs/viewer-gated.pid and none found in /proc")
                return
            kill_viewer(pid)
            gone = not ux.port_busy(PORT)
            check("kill the :8766 server (SIGTERM, SIGKILL after 3 s)", gone, f"pid {pid}, port closed {gone}")
            time.sleep(6)
            state = ux.conn_state(page)
            banner = ux.banner_visible(page)
            check("during the outage: conn-state reconnecting and the banner visible",
                  state == "reconnecting" and banner, f"conn-state {state!r}, banner {banner}")
            new_pid = restart_viewer(token)
            check("restart :8766 with the deploy command and record its pid", bool(new_pid),
                  f"new pid {new_pid}" if new_pid else "no server process found after the restart")
            back = ux.wait_until(lambda: ux.conn_state(page) == "live", 60, 0.5)
            check("after the restart: conn-state returns to live", bool(back), f"conn-state {ux.conn_state(page)!r}")
            ended = ux.wait_until(lambda: ux.feed_info(path)["ended"], 300, 1.0)
            check("replay reached run_end", bool(ended), f"ended {bool(ended)}")
            expected = ux.feed_info(path)["segments"]
            ux.wait_until(lambda: ux.seg_count(page) >= expected, 40, 0.5)
            seqs = page.evaluate(ux.SEQS_JS)
            check("at run_end: rendered segments == feed segments", len(seqs) == expected,
                  f"rendered {len(seqs)}, feed {expected}")
            check("at run_end: no duplicate data-segment-seq", len(set(seqs)) == len(seqs),
                  f"{len(seqs) - len(set(seqs))} duplicate(s) among {len(seqs)}")
        finally:
            browser.close()
    log.close()


def main(argv: list[str] | None = None) -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        url = (URL_FILE.read_text(encoding="utf-8").strip() if URL_FILE.exists() else "") or DEFAULT_URL
    except OSError as exc:
        print(f"FAIL setup: {exc}", flush=True)
        return 2
    if not token:
        print("FAIL setup: empty token file", flush=True)
        return 2
    replay_box: list[subprocess.Popen] = []
    try:
        if not ux.port_busy(PORT):
            print(f"NOTE: nothing listens on :{PORT} at start; restarting it before the check", flush=True)
            restart_viewer(token)
        run_scenario(token, url, replay_box)
    except Exception as exc:
        check("gated: scenario completed", False, f"crashed: {type(exc).__name__}: {str(exc)[:160]}")
    finally:
        for proc in replay_box:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
        if not ux.port_busy(PORT):
            new_pid = restart_viewer(token)
            ensured = ux.port_busy(PORT)
            print(f"  cleanup: :{PORT} was closed, restarted (pid {new_pid}); listening {ensured}", flush=True)
        else:
            print(f"  cleanup: :{PORT} is listening", flush=True)
    passed = sum(1 for _, ok in results if ok)
    failed = [name for name, ok in results if not ok]
    print(f"SUMMARY: {passed}/{len(results)} checks passed; {len(failed)} failed", flush=True)
    for name in failed:
        print(f"  failed: {name}", flush=True)
    return 0 if results and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
