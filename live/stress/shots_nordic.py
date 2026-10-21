#!/usr/bin/env python3
"""Viewport screenshots of noScribe Live: a mid-stream LIVE run and a FINISHED run, each for
dark/light x en/zh-TW x easy off/on at 1440x900 (desktop) and 390x844 (mobile). 32 PNGs in all.

    /usr/bin/python3 -I live/stress/shots_nordic.py [--out DIR] [--static DIR] [--port 8811]
        [--python PY] [--work DIR] [--live-speed 0.2]

Files: OUT/{theme}-{en|zh}-{desktop|mobile}[-easy]-{live|finished}.png, plus OUT/manifest.json with
the state of each shot: segments rendered, whether run_end had reached the page, the theme, easy and
html lang the page applied, and any page errors.

The source is the demo feed (live/feeds/20261020-052449-demo-en-zh.ndjson, copied to WORK). The LIVE
run is replayed at --live-speed (max-gap 2; about 70 s at 0.2) on --port, and each live shot opens a
fresh page while the replay is still going. A shot is mid-stream when some but not all segments are
rendered and run_end has not reached the page; the manifest records it. The FINISHED run is replayed at
speed 8 on --port+1, and each finished shot waits for run_end and every segment. Servers, replays and
the browser are this script's own children; a busy port aborts the run. Server and replay helpers come
from measure_ux.py in this directory.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # live/stress; python -I keeps the script dir off sys.path
sys.path.insert(0, str(HERE))
import measure_ux as mu  # noqa: E402

DEFAULT_OUT = Path("/tmp/nslive-r9m/shots")
DEFAULT_PORT = 8811
FINISHED_SPEED = 8
SIZES = (("desktop", mu.DESKTOP), ("mobile", mu.PHONE))
SHORT_LOCALE = {"en": "en", "zh-TW": "zh"}
EXPECTED_SHOTS = 32


# Reveal state of the live page: segments on screen and the reveal queue (__nsliveReveal.queued).
MID_JS = """() => { const r = window.__nsliveReveal;
  return { segs: document.querySelectorAll('[data-segment-seq]').length, queued: r ? Number(r.queued || 0) : null }; }"""
# Text each segment shows, walked like test_nordic's SAMPLE_JS (unrevealed nodes skipped).
SEG_TEXT_JS = """() => { const out = {};
  for (const el of document.querySelectorAll('[data-segment-seq]')) {
    let txt = ''; const walk = (n) => { for (const c of n.childNodes) {
      if (c.nodeType === 3) txt += c.nodeValue; else if (c.nodeType === 1 && !c.hasAttribute('data-unrevealed')) walk(c); } };
    walk(el); out[el.getAttribute('data-segment-seq')] = txt; }
  return out; }"""
CJK_RE = re.compile(r"[㐀-鿿]")


def finals_of(src: Path) -> dict[str, str]:
    """seq -> final segment text of the source feed (whitespace normalised)."""
    return {str(ev.get("seq")): " ".join(str(ev.get("text") or "").split())
            for ev in mu.load_events(src) if ev.get("type") == "segment"}


def mid_state(page: Any, finals: dict[str, str]) -> dict[str, Any]:
    """Segments on screen, the reveal queue, and how many segments show a strict prefix of their final text.
    The page shows zh-TW where the feed is Simplified, so for CJK text only the length bound is checked."""
    reveal = page.evaluate(MID_JS)
    partial = 0
    for seq, raw in (page.evaluate(SEG_TEXT_JS) or {}).items():
        shown = " ".join(str(raw).split())
        full = finals.get(seq, "")
        if shown and full and shown != full and (full.startswith(shown) or
                                                 (CJK_RE.search(full) and len(shown) < len(full) - 2)):
            partial += 1
    return {"segments": int(reveal["segs"]), "queued": reveal["queued"], "partial": partial}


def shot_name(combo: dict[str, Any], state: str) -> str:
    easy = "-easy" if combo["easy"] else ""
    return f"{combo['theme']}-{SHORT_LOCALE[combo['locale']]}-{combo['size']}{easy}-{state}.png"


def combos() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for theme in mu.THEMES:
        for locale in mu.LOCALES:
            for size, vp in SIZES:
                for easy in (False, True):
                    out.append({"theme": theme, "locale": locale, "size": size, "viewport": vp, "easy": easy})
    return out


def meta(combo: dict[str, Any]) -> dict[str, Any]:
    vp = combo["viewport"]
    return {"theme": combo["theme"], "locale": combo["locale"], "size": combo["size"],
            "easy": combo["easy"], "viewport": f"{vp['width']}x{vp['height']}"}


def page_for(browser: Any, combo: dict[str, Any], errs: list[str]) -> tuple[Any, Any]:
    scripts = mu.page_scripts([mu.INIT_JS, mu.theme_script(combo["theme"])], combo["locale"], combo["easy"])
    return mu.open_page(browser, combo["viewport"], scripts, errs)


def page_facts(page: Any, run_id: str, errs: list[str]) -> dict[str, Any]:
    return {
        "theme_applied": page.evaluate(mu.THEME_READ_JS),
        "easy_applied": page.evaluate(mu.EASY_READ_JS) == "true",
        "html_lang": page.evaluate(mu.LANG_JS),
        "segments_rendered": int(page.evaluate(mu.SEG_COUNT_JS)),
        "run_end_seen": mu.ended_on_page(page, run_id),
        "page_errors": errs[:3],
    }


def shoot_live(rig: mu.Rig, browser: Any, src: Path, finals: dict[str, str], speed: float, idx: int,
               combo: dict[str, Any], out: Path) -> dict[str, Any]:
    """One fresh server and one fresh replay per live shot. The earlier version replayed once for all 16 live shots,
    so by the light-theme shots the run had ended and the shots showed a finished run. Here the page opens while the
    replay is young, and the shot is taken once >= 3 segments are on screen and the reveal is mid-stream (queued > 0
    or a segment shows a strict prefix of its final text) with run_end not yet on the page. The state right before
    the screenshot is recorded in the manifest (queued_at_shot, partial_segments_at_shot, mid_stream)."""
    errs: list[str] = []
    name = shot_name(combo, "live")
    feeds = rig.feeds_dir(f"live-{idx}")
    server = rig.start_server(feeds, f"live-{idx}")
    replay = None
    try:
        replay = rig.start_replay(src, feeds, speed=speed, max_gap=2, tag=f"live-{idx}")
        _path, run_id = rig.replay_run(feeds)
        ctx, page = page_for(browser, combo, errs)
        try:
            page.goto(rig.base, wait_until="domcontentloaded", timeout=30000)

            def mid() -> bool:
                if mu.ended_on_page(page, run_id):
                    return False
                state = mid_state(page, finals)
                return state["segments"] >= 3 and ((state["queued"] or 0) > 0 or state["partial"] > 0)

            reached = mu.poll(mid, 60, 0.05)
            facts = page_facts(page, run_id, errs)
            at_shot = mid_state(page, finals)
            page.screenshot(path=str(out / name))
        finally:
            ctx.close()
    finally:
        rig.stop(replay)
        rig.stop(server)
    mid_stream = (bool(reached) and at_shot["segments"] >= 3 and not facts["run_end_seen"]
                  and ((at_shot["queued"] or 0) > 0 or at_shot["partial"] > 0))
    return {"file": name, "state": "live", **meta(combo), **facts, "mid_stream": mid_stream,
            "queued_at_shot": at_shot["queued"], "partial_segments_at_shot": at_shot["partial"],
            "replay_speed": speed}


def shoot_finished(browser: Any, base: str, run_id: str, expected: int, combo: dict[str, Any], out: Path) -> dict[str, Any]:
    errs: list[str] = []
    name = shot_name(combo, "finished")
    ctx, page = page_for(browser, combo, errs)
    try:
        page.goto(base, wait_until="domcontentloaded", timeout=30000)
        mu.wait_finished(page, run_id, expected)
        facts = page_facts(page, run_id, errs)
        page.screenshot(path=str(out / name))
    finally:
        ctx.close()
    return {"file": name, "state": "finished", **meta(combo), **facts,
            "mid_stream": False, "complete": facts["segments_rendered"] >= expected and facts["run_end_seen"]}


def run_live(rig: mu.Rig, browser: Any, src: Path, finals: dict[str, str], speed: float,
             shots: list[dict[str, Any]], out: Path, records: list[dict[str, Any]],
             errors: list[dict[str, str]]) -> None:
    print(f"== live: {len(shots)} shot(s), one fresh replay each at speed {speed} (max-gap 2)", flush=True)
    for idx, combo in enumerate(shots):
        name = shot_name(combo, "live")
        try:
            rec = shoot_live(rig, browser, src, finals, speed, idx, combo, out)
        except Exception as exc:
            mu.record(errors, f"live {name}", exc)
            continue
        records.append(rec)
        print(f"shot {rec['file']} seg={rec['segments_rendered']} queued={rec['queued_at_shot']} "
              f"partial={rec['partial_segments_at_shot']} mid_stream={rec['mid_stream']} "
              f"run_end={rec['run_end_seen']}", flush=True)
        if not rec["mid_stream"]:
            errors.append({"phase": f"live {name}", "error": "not mid-stream when the shot was taken"})


def run_finished(rig: mu.Rig, browser: Any, src: Path, expected: int, shots: list[dict[str, Any]], out: Path,
                 records: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    feeds = rig.feeds_dir("finished")
    server = rig.start_server(feeds, "finished")
    try:
        replay = rig.start_replay(src, feeds, speed=FINISHED_SPEED, max_gap=2, tag="finished")
        replay.wait(timeout=300)
        _path, run_id = rig.replay_run(feeds)
        print(f"== finished: replay speed {FINISHED_SPEED}, run {run_id}", flush=True)
        for combo in shots:
            try:
                rec = shoot_finished(browser, rig.base, run_id, expected, combo, out)
                records.append(rec)
                print(f"shot {rec['file']} seg={rec['segments_rendered']} run_end={rec['run_end_seen']}", flush=True)
            except Exception as exc:
                mu.record(errors, f"finished {shot_name(combo, 'finished')}", exc)
    finally:
        rig.stop(server)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screenshots of noScribe Live: mid-stream live and finished "
                                                 "runs, dark/light x en/zh x easy off/on x desktop/mobile.")
    parser.add_argument("--static", default=str(HERE.parent / "web" / "dist"),
                        help="built frontend dir with index.html (default: %(default)s)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output dir for the PNGs (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port of the live server; the finished server uses port+1 (default: %(default)s)")
    parser.add_argument("--python", default=mu.DEFAULT_PY, help="python with the server deps (default: %(default)s)")
    parser.add_argument("--work", default=None, help="scratch dir for feeds, logs and the source copy "
                                                     "(default: OUT-work next to OUT)")
    parser.add_argument("--live-speed", type=float, default=2.0,
                        help="replay speed of each live shot's own replay (default: %(default)s)")
    parser.add_argument("--shots", default="",
                        help="comma list of shot names without .png to take, e.g. dark-en-desktop-live,"
                             "light-zh-mobile-live (default: all 32)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, mu._exit_on_term)
    args = parse_args(argv)
    static = Path(args.static).resolve()
    out = Path(args.out).resolve()
    work = Path(args.work).resolve() if args.work else out.parent / (out.name + "-work")
    if not (static / "index.html").is_file():
        print(f"FAIL setup: index.html missing in {static}", flush=True)
        return 2
    if not (mu.FEEDS_SRC / mu.DEMO_NAME).is_file():
        print(f"FAIL setup: source feed missing: {mu.FEEDS_SRC / mu.DEMO_NAME}", flush=True)
        return 2
    for port in (args.port, args.port + 1):
        if mu.port_busy(port):
            print(f"FAIL setup: port {port} already in use; not touching that process", flush=True)
            return 2
    try:
        from playwright.sync_api import sync_playwright  # imported here so a missing package is one clear line
    except ImportError as exc:
        print(f"FAIL setup: playwright is not importable with this python: {exc}", flush=True)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    src = work / "src" / mu.DEMO_NAME
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mu.FEEDS_SRC / mu.DEMO_NAME, src)
    expected = sum(1 for ev in mu.load_events(src) if ev.get("type") == "segment")
    finals = finals_of(src)
    wanted = {x.strip()[:-4] if x.strip().endswith(".png") else x.strip() for x in args.shots.split(",") if x.strip()}
    live_shots = [c for c in combos() if not wanted or shot_name(c, "live")[:-4] in wanted]
    fin_shots = [c for c in combos() if not wanted or shot_name(c, "finished")[:-4] in wanted]
    total = len(live_shots) + len(fin_shots)
    if wanted and total != len(wanted):
        print(f"FAIL setup: unknown shot name(s) in --shots: {sorted(wanted)}", flush=True)
        return 2

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    rig_live = mu.Rig(args.python, args.port, static, work)
    rig_fin = mu.Rig(args.python, args.port + 1, static, work)
    try:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    if live_shots:
                        run_live(rig_live, browser, src, finals, args.live_speed, live_shots, out, records, errors)
                    if fin_shots:
                        run_finished(rig_fin, browser, src, expected, fin_shots, out, records, errors)
                finally:
                    browser.close()
        except Exception as exc:
            mu.record(errors, "browser", exc)
    finally:
        rig_live.reap()
        rig_fin.reap()

    pngs = sorted(p.name for p in out.glob("*.png"))
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "static": str(static),
        "out": str(out),
        "source": str(mu.FEEDS_SRC / mu.DEMO_NAME),
        "source_segments": expected,
        "live_replay": "one fresh server and replay per live shot (max-gap 2)",
        "live_replay_speed": args.live_speed,
        "finished_replay_speed": FINISHED_SPEED,
        "ports": {"live": args.port, "finished": args.port + 1},
        "shots_requested": total,
        "png_count": len(pngs),
        "shots": records,
        "errors": errors,
    }
    out.joinpath("manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    print(f"PNG files ({len(pngs)} of {total} requested) in {out}:", flush=True)
    for name in pngs:
        print(f"  {name}", flush=True)
    print(f"manifest: {out / 'manifest.json'}", flush=True)
    return 0 if not errors and len(pngs) == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
