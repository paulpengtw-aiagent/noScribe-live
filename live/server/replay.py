"""Replay a recorded feed as a new run, to rehearse the demo without the GPU.

    cd live && .venv/bin/python -m server.replay SRC.ndjson [--feeds DIR] [--speed 1.0] [--max-gap 5]

Every run found in SRC is written as a new file ``<feeds>/replay-<timestamp>-<orig run_id>.ndjson``.
Its events get the new run_id and ``t`` set to the time they are written, and run_start gets the
replay process's ``pid`` (so the viewer sees the replay as alive while it runs). Lines keep their order,
and the pause before each line is the original gap divided by ``--speed``, capped at ``--max-gap``
seconds. Each line is flushed as soon as it is written, so the tailer only sees complete lines.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, TextIO

LIVE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FEEDS = LIVE_DIR / "feeds"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def read_events(src: Path) -> list[dict[str, Any]]:
    """Every event object in ``src`` in file order. Lines that cannot be used are reported and skipped."""
    events: list[dict[str, Any]] = []
    with src.open("rb") as fh:
        for lineno, raw in enumerate(fh, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except ValueError as exc:
                print(f"warning: {src.name}:{lineno}: skipped unparseable line ({exc})", file=sys.stderr)
                continue
            if not isinstance(event, dict) or not isinstance(event.get("run_id"), str):
                print(f"warning: {src.name}:{lineno}: skipped line without a run_id", file=sys.stderr)
                continue
            events.append(event)
    return events


def _open_run_file(feeds: Path, stamp: str, orig_run_id: str) -> tuple[str, Path, TextIO]:
    """Create ``replay-<stamp>-<orig>.ndjson`` exclusively. Returns (new run_id, path, open file)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", orig_run_id).strip("_") or "run"
    base = f"replay-{stamp}-{safe}"
    suffix = 1
    while True:
        run_id = base if suffix == 1 else f"{base}-{suffix}"
        path = feeds / f"{run_id}.ndjson"
        try:
            return run_id, path, path.open("x", encoding="utf-8")
        except FileExistsError:
            suffix += 1


def replay_events(
    events: list[dict[str, Any]],
    feeds: Path,
    speed: float,
    max_gap: float,
    stamp: str,
) -> list[tuple[str, Path, int]]:
    """Write ``events`` into ``feeds`` as new runs, paced like the original. Returns (run_id, path, lines) per run."""
    feeds.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, tuple[str, Path, TextIO]] = {}   # original run_id -> (new run_id, path, file)
    counts: dict[str, int] = {}
    previous_t: float | None = None
    try:
        for event in events:
            orig = event["run_id"]
            if orig not in outputs:
                outputs[orig] = _open_run_file(feeds, stamp, orig)
                counts[orig] = 0
            t = _number(event.get("t"))
            if previous_t is not None and t is not None:
                pause = min(max(0.0, t - previous_t) / speed, max_gap)
                if pause > 0:
                    time.sleep(pause)
            if t is not None:
                previous_t = t
            new_id, _path, fh = outputs[orig]
            replayed = dict(event, run_id=new_id, t=time.time())
            if event.get("type") == "run_start":
                replayed["pid"] = os.getpid()     # the replay is the process that is alive while it runs
            fh.write(json.dumps(replayed, ensure_ascii=False) + "\n")
            fh.flush()
            counts[orig] += 1
    finally:
        for _run_id, _path, fh in outputs.values():
            fh.close()
    return [(new_id, path, counts[orig]) for orig, (new_id, path, _fh) in outputs.items()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m server.replay",
        description="Replay a recorded noScribe feed as a new run in the feeds directory.",
    )
    parser.add_argument("src", type=Path, help="recorded feed (.ndjson)")
    parser.add_argument("--feeds", type=Path, default=DEFAULT_FEEDS, help="feeds directory (default: live/feeds)")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier (default: 1.0)")
    parser.add_argument("--max-gap", type=float, default=5.0, help="longest single pause in seconds (default: 5)")
    args = parser.parse_args(argv)
    if args.speed <= 0:
        parser.error("--speed must be positive")
    if args.max_gap < 0:
        parser.error("--max-gap must not be negative")

    events = read_events(args.src)
    if not events:
        print(f"nothing to replay in {args.src}", file=sys.stderr)
        return 1
    started = time.time()
    runs = replay_events(events, args.feeds.resolve(), args.speed, args.max_gap, time.strftime("%Y%m%d-%H%M%S"))
    for run_id, path, count in runs:
        print(f"replayed {count} events as run {run_id} -> {path}")
    print(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
