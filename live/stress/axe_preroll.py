#!/usr/bin/env python3
"""axe check during the pre-roll of a LIVE run, noScribe Live.

While the pre-roll terminal is on screen, axe-core must report no serious or critical violation and
the page must not scroll horizontally. Eight configs: nordic and crimson palette x dark and light theme x en and zh-TW locale, at
1440x900. Expected duration: about 3 to 4 minutes (about 25 s per config: pre-roll wait, 8 s settle,
axe run, screenshot).

Run from the repo root with the system Python that has Playwright:

    /usr/bin/python3 -I -B live/stress/axe_preroll.py [--feed NDJSON] [--port 8940] [--static DIR]
        [--work DIR] [--axe PATH] [--python PY]

Each config starts its own `python -m server` (cwd live/, --port, --feeds WORK/feeds, --static DIR)
and one replay of the feed (`python -m server.replay FEED --feeds WORK/feeds --speed 1 --max-gap 30`).
The feed is only read. Feed lookup: --feed, else the demo feed in /workspace/noScribe-live/live/feeds,
else the newest *demo-en-zh*.ndjson in this repo's live/feeds.

Output: one PASS/FAIL line per config, then `SUMMARY: n/m checks passed`. Exit 0 only if all pass.
Screenshots: WORK/shots/preroll-<palette>-<theme>-<locale>.png. Child processes are killed on exit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent            # live/stress
LIVE = HERE.parent                                # live/: cwd for `python -m server` and `python -m server.replay`
DEFAULT_STATIC = LIVE / "web" / "dist"
DEFAULT_PY = "/workspace/noScribe-live/live/.venv/bin/python"
DEFAULT_AXE = "/tmp/nslive-r5/axe.min.js"
DEFAULT_FEED = Path("/workspace/noScribe-live/live/feeds/20261022-003524-demo-en-zh.ndjson")  # read only
DEFAULT_WORK = Path("/tmp/nslive-axe-preroll")
DEFAULT_PORT = 8940
PALETTES = ("nordic", "crimson")
THEMES = ("dark", "light")
LOCALES = ("en", "zh-TW")
PALETTE_KEY = "noscribe-live-palette"  # matrix dimension; no palette picker in live/web/src yet


def resolve_feed(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    if DEFAULT_FEED.is_file():
        return DEFAULT_FEED
    found = sorted((LIVE / "feeds").glob("*demo-en-zh*.ndjson")) if (LIVE / "feeds").is_dir() else []
    return found[-1] if found else None


def wait_health(port: int, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def spawn(cmd: list[str], log: Path) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=LIVE, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def run_config(p: Any, args: argparse.Namespace, feed: Path, axe_text: str, palette: str, theme: str,
               locale: str) -> dict[str, Any]:
    tag = f"{palette}-{theme}-{locale}"
    feeds = args.work / "feeds" / tag
    shutil.rmtree(feeds, ignore_errors=True)
    feeds.mkdir(parents=True)
    logs = args.work / "logs"
    srv = rep = None
    browser = None
    try:
        srv = spawn([args.python, "-m", "server", "--port", str(args.port), "--feeds", str(feeds),
                     "--static", str(args.static)], logs / f"server-{tag}.log")
        if not wait_health(args.port):
            return {"ok": False, "detail": "server did not answer /api/health"}
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            f"localStorage.setItem('noscribe-live-locale','{locale}');localStorage.setItem('noscribe-live-theme','{theme}');localStorage.setItem('noscribe-live-palette','{palette}')")
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{args.port}/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(1)
        rep = spawn([args.python, "-m", "server.replay", str(feed), "--feeds", str(feeds),
                     "--speed", "1", "--max-gap", "30"], logs / f"replay-{tag}.log")
        page.wait_for_selector('[data-testid=preroll-terminal]', timeout=20000)
        time.sleep(8)
        page.add_script_tag(content=axe_text)
        violations = page.evaluate(
            "async()=>{const r=await axe.run(document,{resultTypes:['violations']});"
            "return r.violations.map(v=>[v.id,v.impact,v.nodes.length])}")
        lines = page.evaluate(
            "document.querySelector('[data-testid=preroll-terminal]').innerText.split('\\n').length")
        scroll = page.evaluate("[document.documentElement.scrollWidth,document.documentElement.clientWidth]")
        shots = args.work / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / f"preroll-{tag}.png"))
        serious = [v for v in violations if v[1] in ("serious", "critical")]
        overflow = scroll[0] > scroll[1]
        return {"ok": not serious and not overflow, "serious": serious, "all": [v[0] for v in violations],
                "lines": lines, "scroll": scroll}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {str(exc).strip()[:300]}"}
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        stop(rep)
        stop(srv)
        time.sleep(0.5)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="axe check during the live pre-roll (nordic/crimson x dark/light x en/zh-TW).")
    parser.add_argument("--feed", default=None, help="recorded feed to replay (default: the demo feed)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port for the server (default: %(default)s)")
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC, help="built frontend dir (has index.html)")
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK, help="scratch dir: feeds, logs, shots")
    parser.add_argument("--axe", type=Path, default=Path(DEFAULT_AXE), help="axe-core script (default: %(default)s)")
    parser.add_argument("--python", default=DEFAULT_PY, help="python with the server deps (default: live venv)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    feed = resolve_feed(args.feed)
    if feed is None or not feed.is_file():
        print(f"FAIL axe preroll: no feed (pass --feed); looked for {DEFAULT_FEED}", flush=True)
        return 2
    if not (args.static / "index.html").is_file():
        print(f"FAIL axe preroll: no index.html in {args.static} (pass --static)", flush=True)
        return 2
    if not args.axe.is_file():
        print(f"FAIL axe preroll: no axe-core script at {args.axe} (pass --axe)", flush=True)
        return 2
    axe_text = args.axe.read_text(encoding="utf-8")
    args.work.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str, str, dict[str, Any]]] = []
    with sync_playwright() as p:
        for palette in PALETTES:
            for theme in THEMES:
                for locale in LOCALES:
                    results.append((palette, theme, locale,
                                    run_config(p, args, feed, axe_text, palette, theme, locale)))
    passed = 0
    for palette, theme, locale, res in results:
        if res.get("ok"):
            passed += 1
        status = "PASS" if res.get("ok") else "FAIL"
        if "detail" in res:
            print(f"{status} axe preroll {palette} {theme} {locale}: {res['detail']}", flush=True)
        else:
            print(f"{status} axe preroll {palette} {theme} {locale}: serious/critical {res['serious']}, "
                  f"all {res['all']}, terminal lines {res['lines']}, scroll {res['scroll']}", flush=True)
    total = len(results)
    print(f"SUMMARY: {passed}/{total} checks passed", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
