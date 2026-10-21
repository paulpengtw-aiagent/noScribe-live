#!/usr/bin/env python3
"""Fresh-load check for Chinese text in noScribe Live (Mac review 7 blocker).

Starts its own server (`python -m server`, cwd live/) on --port, serving the finished demo feed, and opens the bare
URL (Follow newest) in a new browser context for every load. The converter delay (window.__NSLIVE_ZH_DELAY_MS, read
by web/src/lib/zh-tw.ts) and the CPU throttle (CDP Emulation.setCPUThrottlingRate) cycle across the loads, all eight
combinations of DELAYS x THROTTLES in turn. Two seconds after the transcript mounts, every [data-testid="paragraph"] must
have text: at least one segment with text, and every segment that has text must be computed visibility != hidden.
For the 4000 ms delay the check runs again 1 s after the delay. Failing checks are screenshotted.

Only the Playwright browser is started, one at a time. Before each load the cgroup memory is read; above 17.5 GiB
the test waits, and aborts if it stays high. Only the server it spawned is signalled.

Usage (from anywhere):
  /usr/bin/python3 -I -B /workspace/noScribe-live-nordic/live/stress/test_cjk_load.py --port 8900 --loads 32
Exit status 0 when every check passes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PY_DEFAULT = "/workspace/noScribe-live/live/.venv/bin/python"  # the live venv: the server's dependencies (read only)
LIVE_DIR = Path("/workspace/noScribe-live-nordic/live")  # cwd for `python -m server`
STATIC_DEFAULT = LIVE_DIR / "web" / "dist"
FEED_SRC = Path("/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson")  # read only
WORK_DEFAULT = Path("/tmp/nslive-r15r/cjk")
VIEWPORT = {"width": 1440, "height": 900}
DELAYS_MS = (0, 300, 1500, 4000)
THROTTLES = (1, 4)
MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
MEMORY_LIMIT = 18790481920  # 17.5 GiB

# Per paragraph: the segment spans that carry text, and how many of them are computed visible.
PARAGRAPH_JS = """() => {
  const paras = Array.from(document.querySelectorAll('[data-testid="paragraph"]'));
  const bad = [];
  for (const p of paras) {
    const spans = Array.from(p.querySelectorAll('[data-segment-seq]'));
    const withText = spans.filter((s) => (s.textContent || '').trim() !== '');
    const shown = withText.filter((s) => getComputedStyle(s).visibility !== 'hidden');
    if (withText.length === 0 || shown.length !== withText.length) {
      bad.push({ text: (p.textContent || '').trim().slice(0, 60), spans: spans.length,
                 withText: withText.length, shown: shown.length, html: p.innerHTML.slice(0, 240) });
    }
  }
  const zh = window.__nsliveZh ? { ready: window.__nsliveZh.ready, held: window.__nsliveZh.heldSegments } : null;
  return { paragraphs: paras.length, bad, zh };
}"""


def mem_now() -> int:
    return int(MEMORY_CURRENT.read_text().strip())


def wait_memory(max_wait: float) -> bool:
    deadline = time.monotonic() + max_wait
    while mem_now() > MEMORY_LIMIT:
        if time.monotonic() > deadline:
            return False
        time.sleep(2)
    return True


def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_health(port: int, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def start_server(port: int, feeds: Path, static: Path, logs: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k != "LIVE_TOKEN"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [PY_DEFAULT, "-m", "server", "--port", str(port), "--feeds", str(feeds), "--static", str(static)]
    with open(logs / f"server-{port}.log", "ab") as log:
        return subprocess.Popen(cmd, cwd=str(LIVE_DIR), stdout=log, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
    except OSError:
        pass


def check_page(page, label: str, index: int, shots: Path) -> tuple[bool, str]:
    info = page.evaluate(PARAGRAPH_JS)
    bad = info["bad"]
    zh = info["zh"]
    # Stale: the converter is ready, but the transcript's last render still held segments (no re-render on the flip).
    stale = bool(zh and zh["ready"] and zh["held"] > 0)
    ok = info["paragraphs"] > 0 and not bad and not stale
    detail = f"{label}: paragraphs={info['paragraphs']} bad={len(bad)} stale={stale} zh={zh}"
    if not ok:
        shot = shots / f"fail-{index:02d}-{label}.png"
        page.screenshot(path=str(shot))
        detail += f" shot={shot}"
        for item in bad[:3]:
            detail += f"\n      bad paragraph: {item}"
    return ok, detail


def run_load(browser, base: str, index: int, delay: int, throttle: int, shots: Path) -> tuple[bool, list[str]]:
    lines: list[str] = []
    ctx = browser.new_context(viewport=VIEWPORT)
    try:
        ctx.add_init_script(f"window.__NSLIVE_ZH_DELAY_MS = {delay};")
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        page.goto(base, wait_until="load")
        loaded = time.monotonic()
        page.wait_for_selector('[data-testid="paragraph"]', timeout=20000)
        mounted = time.monotonic()
        # The 1.5 s fallback clock starts when the transcript first holds CJK text, which is its mount, not the load
        # event. Under 4x CPU the mount alone can take about a second, so the 2 s check counts from the mount; the
        # 4000 ms case also checks 1 s after the delay ends (from load). mount_ms is printed for each load.
        checks = [(f"2s after mount (mount {round((mounted - loaded) * 1000)}ms after load)", mounted + 2.0)]
        if delay == 4000:
            checks.append(("delay+1s after load", loaded + delay / 1000 + 1.0))
        all_ok = True
        for label, due in checks:
            wait = due - time.monotonic()
            if wait > 0:
                page.wait_for_timeout(int(wait * 1000))
            ok, detail = check_page(page, label, index, shots)
            all_ok = all_ok and ok
            lines.append(("PASS " if ok else "FAIL ") + detail)
        return all_ok, lines
    except Exception as exc:  # a load that cannot be checked is a failure, not a skip
        lines.append(f"FAIL load error: {exc!r}")
        return False, lines
    finally:
        ctx.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--work", type=Path, default=WORK_DEFAULT)
    parser.add_argument("--static", type=Path, default=STATIC_DEFAULT, help="built frontend dir (has index.html)")
    parser.add_argument("--loads", type=int, default=32, help="fresh page loads (default 32: 4 per delay/throttle pair)")
    parser.add_argument("--max-seconds", type=float, default=600.0, help="stop starting loads after this many seconds")
    args = parser.parse_args()

    if port_busy(args.port):
        print(f"FAIL setup: port {args.port} already in use; not touching that process", flush=True)
        return 2
    if not FEED_SRC.is_file():
        print(f"FAIL setup: demo feed missing: {FEED_SRC}", flush=True)
        return 2
    if not (args.static / "index.html").is_file():
        print(f"FAIL setup: {args.static}/index.html is missing; run pnpm build first", flush=True)
        return 2

    work = args.work
    feeds, shots, logs = work / "feeds", work / "shots", work / "logs"
    for directory in (feeds, shots, logs):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FEED_SRC, feeds / FEED_SRC.name)

    from playwright.sync_api import sync_playwright  # imported here so --help works without Playwright

    proc = start_server(args.port, feeds, args.static.resolve(), logs)
    started = time.monotonic()
    failures: list[tuple[int, int, int]] = []
    passed = 0
    ran = 0
    try:
        if not wait_health(args.port):
            print(f"FAIL setup: server on port {args.port} did not answer /api/health (logs in {logs})", flush=True)
            return 2
        base = f"http://127.0.0.1:{args.port}/"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for index in range(args.loads):
                    if time.monotonic() - started > args.max_seconds:
                        print(f"STOP time limit reached after {ran} loads", flush=True)
                        break
                    if not wait_memory(120):
                        print(f"ABORT memory.current {mem_now()} stays above {MEMORY_LIMIT} (17.5 GiB)", flush=True)
                        break
                    delay = DELAYS_MS[index % len(DELAYS_MS)]
                    throttle = THROTTLES[(index // len(DELAYS_MS)) % len(THROTTLES)]
                    ok, lines = run_load(browser, base, index, delay, throttle, shots)
                    ran += 1
                    passed += ok
                    if not ok:
                        failures.append((index, delay, throttle))
                    print(f"load {index:02d} delay={delay:>4}ms cpu={throttle}x " + ("ok" if ok else "FAILED"), flush=True)
                    for line in lines:
                        print(f"    {line}", flush=True)
            finally:
                browser.close()
    finally:
        stop_server(proc)

    print("", flush=True)
    print("summary by delay/throttle (passed/loads):", flush=True)
    for delay in DELAYS_MS:
        for throttle in THROTTLES:
            combo = [i for i in range(ran) if DELAYS_MS[i % len(DELAYS_MS)] == delay
                     and THROTTLES[(i // len(DELAYS_MS)) % len(THROTTLES)] == throttle]
            fails = sum(1 for i, d, t in failures if d == delay and t == throttle)
            print(f"  delay={delay:>4}ms cpu={throttle}x: {len(combo) - fails}/{len(combo)}", flush=True)
    print(f"RESULT {passed}/{ran} loads passed, {len(failures)} failed, in {time.monotonic() - started:.0f}s", flush=True)
    return 0 if ran > 0 and not failures else 1


if __name__ == "__main__":
    sys.exit(main())
