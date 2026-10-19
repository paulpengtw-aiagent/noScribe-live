"""Command-line entry point: ``python -m server`` (run it from the live/ directory)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from .app import create_app

LIVE_DIR = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m server",
        description="Serve the noScribe Live viewer and the feed API it reads.",
    )
    parser.add_argument(
        "--feeds", type=Path, default=LIVE_DIR / "feeds",
        help="directory where the noScribe CLI writes *.ndjson feeds (default: live/feeds)",
    )
    parser.add_argument(
        "--static", type=Path, default=LIVE_DIR / "web" / "dist",
        help="built frontend directory containing index.html (default: live/web/dist)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    parser.add_argument("--poll", type=float, default=0.05, help="feed poll interval in seconds (default: 0.05)")
    args = parser.parse_args(argv)

    # uvicorn configures only its own loggers, so set up the root logger for our INFO lines.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = create_app(args.feeds.resolve(), args.static.resolve(), args.poll)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
