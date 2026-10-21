#!/usr/bin/env python3
"""Orb pin test: the activity orb's container never moves or resizes except during the switch.

Real-speed replay, page opened before the run starts, at 1440x900 and 390x844:
  * the pre-roll orb box ([data-orb-slot="preroll"]) is sampled every 100 ms until the switch (exitedAt);
  * the stage orb box ([data-orb-slot="stage"]) is sampled from exitedAt + 1.5 s for 20 s of streaming.
Every sample must match the first sample of its phase within +-0.5 px (x, y, width, height).
The single switch window (exitedAt .. exitedAt + 1.5 s) is exempt.

    python3 live/stress/test_orb_pin.py

Needs the built app in live/web/dist (npm run build) and playwright in the python3 environment.
Prints PASS/FAIL per check and a SUMMARY line; exit code 0 only when every check passes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent  # .../live/stress
LIVE = HERE.parent  # .../live
DIST = LIVE / "web" / "dist"
WORK_ROOT = Path("/tmp/nslive-f/orb-pin")
VENV_PY = "/workspace/noScribe-live/live/.venv/bin/python"  # used read-only: only the interpreter
FEED = "/workspace/noScribe-live/live/feeds/20261022-003524-demo-en-zh.ndjson"  # read-only source feed
PORT = 8971
TOL_PX = 0.5
SWITCH_WINDOW_MS = 1500
STREAM_MS = 20000
MAX_WAIT_S = 150.0
SAMPLE_S = 0.1
VIEWPORTS = [(1440, 900), (390, 844)]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # keep bytecode out of the read-only venv

SAMPLE_JS = """() => {
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return r.width > 0 ? [r.left, r.top, r.width, r.height] : null;
  };
  return {
    t: Date.now(),
    pre: box('[data-orb-slot="preroll"]'),
    stage: box('[data-orb-slot="stage"]'),
    probe: window.__nslivePreroll || null,
  };
}"""


def wait_health(port: int, timeout: float = 25.0) -> None:
    url = f"http://127.0.0.1:{port}/api/health"
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server on port {port} did not answer {url}")


def drift(box: list[float], ref: list[float]) -> float:
    return max(abs(a - b) for a, b in zip(box, ref))


def check_static(name: str, rows: list[dict], key: str) -> tuple[bool, str]:
    if len(rows) < 10:
        return False, f"{name}: only {len(rows)} samples"
    ref = rows[0][key]
    worst = max(drift(r[key], ref) for r in rows)
    ok = worst <= TOL_PX
    return ok, f"{name}: {len(rows)} samples, max drift {worst:.2f} px (tolerance {TOL_PX} px)"


def run_viewport(width: int, height: int) -> dict:
    tag = f"{width}x{height}"
    work = WORK_ROOT / tag
    shutil.rmtree(work, ignore_errors=True)
    feeds = work / "feeds"
    feeds.mkdir(parents=True)
    server_log = open(work / "server.log", "w", encoding="utf-8")
    server = subprocess.Popen(
        [VENV_PY, "-m", "server", "--port", str(PORT), "--feeds", str(feeds), "--static", str(DIST)],
        cwd=str(LIVE), env=ENV, stdout=server_log, stderr=subprocess.STDOUT,
    )
    replay = None
    replay_log = None
    samples: list[dict] = []
    try:
        wait_health(PORT)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    is_mobile=width < 600,
                    has_touch=width < 600,
                    locale="zh-TW",
                    color_scheme="dark",
                    reduced_motion="no-preference",
                )
                ctx.add_init_script(
                    "try { localStorage.setItem('noscribe-live-theme', 'dark');"
                    " localStorage.setItem('noscribe-live-locale', 'zh-TW'); } catch (e) {}"
                )
                page = ctx.new_page()
                page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)  # the app mounts and opens its stream before the run starts
                replay_log = open(work / "replay.log", "w", encoding="utf-8")
                replay = subprocess.Popen(
                    [VENV_PY, "-m", "server.replay", FEED, "--feeds", str(feeds), "--speed", "1", "--max-gap", "30"],
                    cwd=str(LIVE), env=ENV, stdout=replay_log, stderr=subprocess.STDOUT,
                )
                deadline = time.time() + MAX_WAIT_S
                stop_ms: float | None = None
                while time.time() < deadline:
                    st = page.evaluate(SAMPLE_JS)
                    samples.append(st)
                    probe = st.get("probe") or {}
                    if stop_ms is None and probe.get("exitedAt") is not None:
                        stop_ms = probe["exitedAt"] + SWITCH_WINDOW_MS + STREAM_MS
                    if stop_ms is not None and st["t"] >= stop_ms:
                        break
                    time.sleep(SAMPLE_S)
                ctx.close()
            finally:
                browser.close()
    finally:
        if replay is not None and replay.poll() is None:
            replay.terminate()
            replay.wait(5)
        server.terminate()
        try:
            server.wait(5)
        except subprocess.TimeoutExpired:
            server.kill()
        server_log.close()
        if replay_log is not None:
            replay_log.close()

    exit_ms = next(
        ((s.get("probe") or {}).get("exitedAt") for s in samples if (s.get("probe") or {}).get("exitedAt") is not None),
        None,
    )
    pre_rows = [s for s in samples if s["pre"] and (exit_ms is None or s["t"] < exit_ms)]
    post_rows = []
    if exit_ms is not None:
        start = exit_ms + SWITCH_WINDOW_MS
        post_rows = [s for s in samples if s["stage"] and start <= s["t"] <= start + STREAM_MS]
    checks = []
    ok, msg = check_static("pre-roll orb", pre_rows, "pre")
    checks.append((ok, f"{tag} {msg}"))
    if exit_ms is None:
        checks.append((False, f"{tag} switch never observed (exitedAt unset)"))
    else:
        ok, msg = check_static("stage orb (20 s streaming)", post_rows, "stage")
        checks.append((ok, f"{tag} {msg}"))
    (work / "samples.json").write_text(__import__("json").dumps(samples), encoding="utf-8")
    return {"tag": tag, "checks": checks, "samples": len(samples), "exit_ms": exit_ms}


def main() -> int:
    results = []
    for width, height in VIEWPORTS:
        try:
            res = run_viewport(width, height)
        except Exception as exc:  # report the viewport as failed, keep going
            res = {"tag": f"{width}x{height}", "checks": [(False, f"{width}x{height} error: {exc}")], "samples": 0}
        results.append(res)
        for ok, msg in res["checks"]:
            print(("PASS " if ok else "FAIL ") + msg)
    passed = sum(1 for res in results for ok, _ in res["checks"] if ok)
    total = sum(len(res["checks"]) for res in results)
    print(f"SUMMARY: {passed}/{total} checks PASS (switch window exempt: exitedAt .. +{SWITCH_WINDOW_MS} ms)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
