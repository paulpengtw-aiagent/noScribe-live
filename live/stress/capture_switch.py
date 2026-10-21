#!/usr/bin/env python3
"""Record the pre-roll -> full UI switch at real speed, then cut stills and a 4x2 contact sheet from the video.

    python3 live/stress/capture_switch.py --width 1440 --height 900 --locale zh --port 8965

Order of work (one browser at a time):
  1. own viewer server on --port, reading a fresh feeds dir under /tmp/nslive-r4v/<tag>/feeds;
  2. a Playwright context that records video at the viewport size; the page is opened first;
  3. only then `python -m server.replay FEED --speed 1 --max-gap 30` (real speed);
  4. poll window.__nslivePreroll until exitedAt is set, keep recording --after seconds past it, close the
     context (this flushes the .webm), then kill the replay and the server;
  5. map wall-clock to video time with t0 = midpoint of time.time() around ctx.new_page(), cut the stills
     at switch-0.5 .. switch+2.0 s plus one pre-roll still while the diarization line is running, and tile
     them 4x2. Stills go to live/docs/showreel/, the .webm stays in /tmp unless it is under 2 MB.

Time bases: the app sets exitedAt from Date.now() (epoch ms) on a 250 ms tick, so it can lag the real render
by up to 250 ms. performance.now() terms are exitedAt - performance.timeOrigin.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

WT = Path("/workspace/noScribe-live-showreel")
LIVE = WT / "live"
DIST = LIVE / "web" / "dist"
OUT = LIVE / "docs" / "showreel"
VENV_PY = "/workspace/noScribe-live/live/.venv/bin/python"  # used read-only: only the interpreter
FEED = "/workspace/noScribe-live/live/feeds/20261022-003524-demo-en-zh.ndjson"  # read-only source feed
WORK_ROOT = Path("/tmp/nslive-r4v")
OFFSETS = [-0.5, 0.15, 0.3, 0.5, 0.8, 1.2, 2.0]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # keep bytecode out of the read-only venv

PROBE_JS = """() => {
  const probe = window.__nslivePreroll || null;
  return {
    origin: performance.timeOrigin,
    probe: probe,
    lines: Array.from(document.querySelectorAll('[data-testid="preroll-line"]')).map((e) => e.getAttribute('data-line')),
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


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def duration_of(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return round(float(out.stdout.strip()), 3)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def capture(a: argparse.Namespace) -> dict:
    app_locale = "zh-TW" if a.locale == "zh" else "en"
    pw_locale = "zh-TW" if a.locale == "zh" else "en-US"
    tag = f"{a.width}-{a.locale}"
    mobile = a.width < 600
    work = WORK_ROOT / tag
    shutil.rmtree(work, ignore_errors=True)
    feeds, vdir, logs = work / "feeds", work / "video", work / "logs"
    for d in (feeds, vdir, logs):
        d.mkdir(parents=True)
    rec: dict = {"tag": tag, "viewport": [a.width, a.height], "app_locale": app_locale, "port": a.port}

    server_log = open(logs / "server.log", "w", encoding="utf-8")
    server = subprocess.Popen(
        [VENV_PY, "-m", "server", "--port", str(a.port), "--feeds", str(feeds), "--static", str(DIST)],
        cwd=str(LIVE), env=ENV, stdout=server_log, stderr=subprocess.STDOUT,
    )
    replay = None
    replay_log = None
    video_src: Path | None = None
    enter = exit_ = diar = None
    polls = 0
    t0 = 0.0
    try:
        wait_health(a.port)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                ctx = browser.new_context(
                    viewport={"width": a.width, "height": a.height},
                    device_scale_factor=1,
                    is_mobile=mobile,
                    has_touch=mobile,
                    locale=pw_locale,
                    color_scheme="dark",
                    reduced_motion="no-preference",
                    record_video_dir=str(vdir),
                    record_video_size={"width": a.width, "height": a.height},
                )
                ctx.add_init_script(
                    "try { localStorage.setItem('noscribe-live-theme', 'dark');"
                    f" localStorage.setItem('noscribe-live-locale', {json.dumps(app_locale)}); }} catch (e) {{}}"
                )
                t_a = time.time()
                page = ctx.new_page()
                t_b = time.time()
                t0 = (t_a + t_b) / 2  # video t=0 lies between these two instants
                rec["t0_wall"] = t0
                page.goto(f"http://127.0.0.1:{a.port}/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)  # let the app mount and open its stream before the run starts

                replay_log = open(logs / "replay.log", "w", encoding="utf-8")
                rec["replay_start_video_s"] = round(time.time() - t0, 3)
                replay = subprocess.Popen(
                    [VENV_PY, "-m", "server.replay", FEED, "--feeds", str(feeds), "--speed", "1", "--max-gap", "30"],
                    cwd=str(LIVE), env=ENV, stdout=replay_log, stderr=subprocess.STDOUT,
                )

                stop_at = None
                deadline = time.time() + a.max_wait
                while True:
                    now = time.time()
                    st = page.evaluate(PROBE_JS)
                    polls += 1
                    probe = st.get("probe") or {}
                    lines = st.get("lines") or []
                    if enter is None and probe.get("enteredAt") is not None:
                        enter = {"wall": now, "epoch_ms": probe["enteredAt"], "reason": probe.get("reason")}
                    if diar is None and ("segmentation" in lines or "embeddings" in lines) and "speakers" not in lines:
                        diar = {"wall": now, "lines": lines}
                    if exit_ is None and probe.get("exitedAt") is not None:
                        origin = st["origin"]
                        exit_ = {
                            "wall": now,
                            "epoch_ms": probe["exitedAt"],
                            "origin_ms": origin,
                            "perf_ms": probe["exitedAt"] - origin,
                            "reason": probe.get("reason"),
                        }
                        stop_at = probe["exitedAt"] / 1000.0 + a.after
                    if stop_at is not None and now >= stop_at:
                        break
                    if now > deadline:
                        break
                    time.sleep(0.03)
                ctx.close()  # flushes the video
                video_src = Path(page.video.path())
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

    rec["polls"] = polls
    rec["enter_wall_minus_t0"] = round(enter["wall"] - t0, 3) if enter else None
    rec["diar_wall_minus_t0"] = round(diar["wall"] - t0, 3) if diar else None
    rec["diar_lines"] = diar["lines"] if diar else None
    rec["exit"] = exit_
    if video_src is None:
        rec["error"] = "no video produced"
        return rec
    video = work / f"switch-{tag}.webm"
    shutil.move(str(video_src), str(video))
    rec["video"] = str(video)
    rec["video_bytes"] = video.stat().st_size
    rec["video_duration_s"] = duration_of(video)
    if exit_ is None:
        rec["error"] = "exitedAt never observed before --max-wait"
        return rec

    switch_v = exit_["epoch_ms"] / 1000.0 - t0  # switch in video seconds
    rec["switch_video_s"] = round(switch_v, 3)
    rec["exit_perf_ms"] = round(exit_["perf_ms"], 1)
    rec["enter_video_s"] = round(enter["wall"] - t0, 3) if enter else None

    if diar is not None:
        pre_t, pre_name = diar["wall"] - t0, f"preroll-{tag}-diarizing.png"
    else:  # diarization line never seen: fall back to the middle of the pre-roll
        start = (enter["wall"] if enter else exit_["wall"]) - t0
        pre_t, pre_name = (start + switch_v) / 2, f"preroll-{tag}-mid.png"
    stills = [(pre_name, pre_t)] + [(f"switch-{tag}-{off:+.2f}s.png", switch_v + off) for off in OFFSETS]

    OUT.mkdir(parents=True, exist_ok=True)
    for name, t in stills:
        ffmpeg("-i", str(video), "-ss", f"{max(t, 0.0):.3f}", "-frames:v", "1", str(OUT / name))

    sheet_dir = work / "sheet"
    sheet_dir.mkdir()
    for i, (name, _) in enumerate(stills, 1):
        shutil.copyfile(OUT / name, sheet_dir / f"{i:02d}.png")
    ffmpeg(
        "-framerate", "1", "-i", str(sheet_dir / "%02d.png"),
        "-vf", f"scale={260 if mobile else 480}:-2,tile=4x2", "-frames:v", "1",
        str(OUT / f"switch-{tag}-sheet.png"),
    )
    if video.stat().st_size < 2 * 1024 * 1024:
        shutil.copyfile(video, OUT / f"switch-{tag}.webm")
        rec["webm_copied_to"] = str(OUT / f"switch-{tag}.webm")
    rec["stills"] = [{"file": str(OUT / name), "video_s": round(t, 3)} for name, t in stills]
    rec["sheet"] = str(OUT / f"switch-{tag}-sheet.png")
    (work / "timeline.json").write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--locale", choices=["zh", "en"], default="zh")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--after", type=float, default=4.0, help="seconds to keep recording after exitedAt")
    ap.add_argument("--max-wait", type=float, default=150.0, help="stop waiting for exitedAt after this many seconds")
    a = ap.parse_args()
    rec = capture(a)
    print(json.dumps(rec, indent=2, default=str))
    return 0 if "error" not in rec else 1


if __name__ == "__main__":
    raise SystemExit(main())
