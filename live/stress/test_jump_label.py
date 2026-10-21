#!/usr/bin/env python3
"""Jump button label while a run is live (noScribe Live).

While the run is live, a reader who has scrolled up must see "Jump to live" (en) or "回到即時" (zh-TW) on every
sample; "Jump to end" / "跳至結尾" may appear only once run_end is in the feed, and must appear soon after.
Three pages watch one replay in one browser: English desktop, zh-TW desktop, and English Easy view at 390 px.

    /usr/bin/python3 -I live/stress/test_jump_label.py [--port 8911] [--speed 0.5] [--max-gap 30] [--work DIR] [--static DIR]

Starts `python -m server` on --port (fresh feeds dir) and `python -m server.replay SRC --speed S --max-gap G`.
SRC is copied into WORK, so the recorded feed stays read only. Samples the label every 500 ms until run_end is in
the feed file, then up to 20 s more (the end label must show within 15 s of run_end, since the page drains its queue after run_end). Exit 0 only if every check passed. Waits (up to 3 min) while the cgroup memory is
above 18.0 GiB, and exits 2 if it never drops.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
LIVE = HERE.parent
sys.path.insert(0, str(HERE))  # run under -I: the script directory is not on sys.path
from test_ux import wait_full_ui  # noqa: E402  (pre-roll wait; same directory)
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_SRC = "/workspace/noScribe-live/live/feeds/20261020-052449-demo-en-zh.ndjson"
MEM_CURRENT = Path("/sys/fs/cgroup/memory.current")
MEM_LIMIT = 19327352832  # 18.0 GiB

LIVE_LABEL = {"en": "Jump to live", "zh-TW": "回到即時"}
END_LABEL = {"en": "Jump to end", "zh-TW": "跳至結尾"}
SEG_JS = "() => document.querySelectorAll('[data-segment-index]').length"
SCROLLER = '[data-testid="transcript-scroll"]'
JUMP = '[data-testid="jump-to-live"]'


def memory_ok() -> bool:
    end = time.monotonic() + 180
    while True:
        cur = int(MEM_CURRENT.read_text())
        if cur <= MEM_LIMIT:
            print(f"memory.current {cur}: ok")
            return True
        if time.monotonic() >= end:
            print(f"memory.current {cur}: still above the limit after 3 min, not starting a browser")
            return False
        print(f"memory.current {cur}: above the limit, polling in 15 s")
        time.sleep(15)


def api_runs(port: int) -> list[dict]:
    try:
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs", timeout=2))
    except Exception:
        return []


def following_of(page) -> str | None:
    return page.evaluate("() => { const el = document.querySelector('[data-testid=\"transcript-scroll\"]'); return el ? el.dataset.following : null; }")


def wait_until(fn, timeout: float, step: float = 0.2):
    end = time.monotonic() + timeout
    while True:
        try:
            value = fn()
        except Exception:  # page still loading, feed line half written
            value = None
        if value or time.monotonic() >= end:
            return value
        time.sleep(step)


def main() -> int:
    ap = argparse.ArgumentParser(description="Jump button label while a run is live")
    ap.add_argument("--port", type=int, default=8911)
    ap.add_argument("--speed", type=float, default=0.5)
    ap.add_argument("--max-gap", type=float, default=30.0,
                    help="longest single replay pause in seconds (default 30: keeps the run live through the pre-roll)")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--python", default=DEFAULT_PY)
    ap.add_argument("--static", default=str(LIVE / "web" / "dist"))
    ap.add_argument("--work", default="/tmp/nslive-r17/jump")
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--min-live", type=int, default=8, help="live samples (500 ms apart) each page must take")
    args = ap.parse_args()
    if not memory_ok():
        return 2

    port = args.port
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    feeds = work / "feeds"
    feeds.mkdir(parents=True)
    src = work / "src" / Path(args.src).name
    src.parent.mkdir(parents=True)
    shutil.copy(args.src, src)

    results: list[bool] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append(bool(ok))
        print(("PASS" if ok else "FAIL"), name, "-", detail)

    srv = subprocess.Popen([args.python, "-m", "server", "--port", str(port), "--feeds", str(feeds), "--static", args.static],
                           cwd=LIVE, stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    rep = None
    try:
        up = wait_until(lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).status == 200, 20)
        if not up:
            check("server up", False, "no /api/health answer")
            return 1
        before = set(os.listdir(feeds))
        rep = subprocess.Popen([args.python, "-m", "server.replay", str(src), "--feeds", str(feeds),
                                "--speed", str(args.speed), "--max-gap", str(args.max_gap)],
                               cwd=LIVE, stdout=open(work / "replay.log", "w"), stderr=subprocess.STDOUT)
        path = wait_until(lambda: next((feeds / f for f in os.listdir(feeds) if f not in before and f.endswith(".ndjson")), None), 20, 0.2)
        if path is None:
            check("replay run file", False, "no new feed file")
            return 1
        run_id = path.stem

        def ended() -> bool:
            return any(json.loads(line).get("type") == "run_end"
                       for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

        with sync_playwright() as p:
            browser = p.chromium.launch()
            specs = [
                ("en", "en-US", "en", "0", {"width": 1280, "height": 800}),
                ("zh-TW", "zh-TW", "zh-TW", "0", {"width": 1280, "height": 800}),
                ("easy", "en-US", "en", "1", {"width": 390, "height": 844}),
            ]
            pages = {}
            for name, locale, loc, easy, vp in specs:
                ctx = browser.new_context(viewport=vp, locale=locale)
                ctx.add_init_script(f"localStorage.setItem('noscribe-live-locale','{loc}');"
                                    f"localStorage.setItem('noscribe-live-theme','light');"
                                    f"localStorage.setItem('noscribe-live-easy','{easy}')")
                page = ctx.new_page()
                page.goto(f"http://127.0.0.1:{port}/?run={run_id}", wait_until="domcontentloaded", timeout=30000)
                pages[name] = (ctx, page, loc)

            for name, (ctx, page, loc) in pages.items():
                wait_full_ui(page, 90)
                ready = wait_until(lambda: page.evaluate(SEG_JS) >= 8 and following_of(page) == "true", 90, 0.2)
                check(f"{name}: >= 8 segments with following=true", bool(ready), f"segments {page.evaluate(SEG_JS)}")
                if not ready:
                    return 1
                box = page.locator(SCROLLER).bounding_box()
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.wheel(0, -100)  # scroll up while live
                detached = wait_until(lambda: following_of(page) == "false", 3, 0.05)
                check(f"{name}: scrolled up while live", bool(detached), f"following {following_of(page)!r}, run_end in feed {ended()}")

            t0 = time.monotonic()
            live_n = {name: 0 for name in pages}
            bad: dict[str, list[str]] = {name: [] for name in pages}
            seen_end: dict[str, float] = {}
            transitions: list[str] = []
            last: dict[str, str | None] = {name: None for name in pages}
            fin_at = None
            while time.monotonic() - t0 < args.timeout:
                fin = ended()
                if fin and fin_at is None:
                    fin_at = time.monotonic() - t0
                status = next((r.get("status") for r in api_runs(port) if r.get("run_id") == run_id), None)
                now = time.monotonic() - t0
                for name, (ctx, page, loc) in pages.items():
                    jump = page.locator(JUMP)
                    label = jump.first.text_content().strip() if jump.count() and jump.first.is_visible() else None
                    if label != last[name]:
                        transitions.append(f"{now:6.1f}s {name} {label!r} (run_end in feed {fin}, server status {status!r})")
                        last[name] = label
                    if not fin:
                        if label == LIVE_LABEL[loc]:
                            live_n[name] += 1
                        else:
                            bad[name].append(f"{now:.1f}s label {label!r} while live (server status {status!r})")
                    elif label == END_LABEL[loc] and name not in seen_end:
                        seen_end[name] = now
                done = fin and all(name in seen_end for name in pages)
                if done or (fin and now - fin_at > 20):
                    break
                time.sleep(0.5)

            for name, (ctx, page, loc) in pages.items():
                check(f"{name}: 'Jump to live' on every live sample", not bad[name] and live_n[name] >= args.min_live,
                      f"{live_n[name]} live samples, violations {len(bad[name])}" + (f", first {bad[name][0]}" if bad[name] else ""))
                check(f"{name}: 'Jump to end' only after run_end, and within 15 s of it",
                      name in seen_end and fin_at is not None and seen_end[name] - fin_at <= 15,
                      f"run_end at {fin_at:.1f} s, end label at {seen_end.get(name, float('nan')):.1f} s"
                      if fin_at is not None else "run_end never reached")
            print(f"live window: scroll-up to run_end about {fin_at:.1f} s" if fin_at is not None else "live window: run_end not reached")
            print("label timeline (changes only):")
            for line in transitions:
                print("  " + line)
            for ctx, page, loc in pages.values():
                ctx.close()
            browser.close()
    finally:
        for proc in (rep, srv):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    ok = bool(results) and all(results)
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
