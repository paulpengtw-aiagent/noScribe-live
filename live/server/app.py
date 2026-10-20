"""FastAPI app for noScribe Live: JSON API, live SSE stream, waveform peaks, static frontend."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from .auth import TokenGate
from .feed import FeedTailer, RunRegistry, drain_queue
from .peaks import AudioDecodeError, compute_peaks

logger = logging.getLogger("server.app")

HEARTBEAT_S = 15.0          # "ping" event interval on an open stream (EventSource cannot see comments)
STATUS_CHECK_S = 2.0        # how often run statuses are checked for changes (e.g. a killed CLI goes stale)
DISCONNECT_CHECK_S = 1.0    # an idle stream checks for a departed client this often
PEAKS_CACHE_MAX = 32        # cached peak results (entries, not bytes)

# Sent right after "retry:". A proxy or tunnel may hold a small response until its buffer fills; this
# padding fills it at once. EventSource ignores comment lines.
SSE_OPENING_PADDING = ":" + " " * 2048 + "\n\n"

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>noScribe Live</title>
<style>body{font:16px system-ui,sans-serif;margin:3rem;color:#222}code{background:#f2f2f2;padding:.1em .3em}</style>
</head>
<body>
<h1>noScribe Live</h1>
<p>Frontend not built yet — run <code>live/run.sh</code>.</p>
<p>The API is already up: <a href="/api/health">/api/health</a>, <a href="/api/runs">/api/runs</a>.</p>
</body>
</html>
"""


def sse(event: str, data: Any) -> str:
    """Format one Server-Sent Events message. json.dumps escapes newlines, so the data stays on one line."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _snapshot(registry: RunRegistry, run_id: str | None) -> dict[str, Any]:
    """Catch-up payload for one run: its summary and every event so far."""
    run = registry.get(run_id) if run_id else None
    return {
        "run_id": run_id,
        "summary": run.summary(time.time()) if run is not None else None,
        "events": run.events if run is not None else [],
    }


async def _sse_messages(request: Request, registry: RunRegistry, run_param: str) -> AsyncIterator[str]:
    """Body of GET /api/stream: hello, snapshot, then live updates until the client leaves.

    In ``latest`` mode the stream follows the newest run and switches to a newer one with
    a fresh snapshot. Otherwise it follows the run id it was given.
    """
    loop = asyncio.get_running_loop()
    follow_latest = run_param == "latest"
    followed = registry.latest_run_id if follow_latest else run_param

    # Subscribe and build the opening messages in one synchronous step. Anything ingested
    # after this point is queued; anything before it is in the snapshot. Nothing is lost or repeated.
    queue = registry.subscribe()
    try:
        opening = [
            "retry: 1500\n\n",
            SSE_OPENING_PADDING,
            sse("hello", {"server_t": time.time(), "runs": registry.summaries()}),
            sse("snapshot", _snapshot(registry, followed)),
        ]
        for message in opening:
            yield message

        last_ping = loop.time()
        while True:
            if await request.is_disconnected():
                return
            try:
                kind, run_id, payload = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK_S)
            except asyncio.TimeoutError:
                if loop.time() - last_ping >= HEARTBEAT_S:
                    last_ping = loop.time()
                    yield sse("ping", {"t": time.time()})
                continue

            if kind == "dropped":
                # We fell too far behind. End the stream; EventSource reconnects and catches up from a snapshot.
                return

            if follow_latest and registry.latest_run_id != followed:
                # A newer run has started. Drop what is queued: it is all inside the snapshot built
                # right after the drain, which is synchronous, so nothing is missed.
                drain_queue(queue)
                followed = registry.latest_run_id
                switch = [
                    sse("runs", {"runs": registry.summaries()}),
                    sse("snapshot", _snapshot(registry, followed)),
                ]
                for message in switch:
                    yield message
                continue

            if kind == "runs":
                yield sse("runs", {"runs": registry.summaries()})
                continue
            if payload.get("type") in ("run_start", "run_end"):
                yield sse("runs", {"runs": registry.summaries()})
            if run_id == followed:
                yield sse("feed", {"run_id": run_id, "event": payload})
    finally:
        registry.unsubscribe(queue)


async def _watch_statuses(registry: RunRegistry) -> None:
    """Every STATUS_CHECK_S seconds, publish a change to the open streams when a run's status changed."""
    while True:
        try:
            registry.check_status_changes()
        except Exception:  # one bad check must not stop the watcher
            logger.exception("status check failed; will retry")
        await asyncio.sleep(STATUS_CHECK_S)


def create_app(feeds_dir: str | Path, static_dir: str | Path, poll: float = 0.05, token: str | None = None) -> FastAPI:
    """Build the app. The feed tailer starts and stops with the app's lifespan.

    With a non-empty ``token`` every HTTP path needs it (see ``server.auth``); otherwise nothing is gated.
    """
    feeds_path = Path(feeds_dir)
    static_path = Path(static_dir)
    registry = RunRegistry()
    tailer = FeedTailer(feeds_path, poll, registry)
    peaks_cache: OrderedDict[tuple[str, float, int], dict[str, Any]] = OrderedDict()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        tailer.start()
        watcher = asyncio.get_running_loop().create_task(_watch_statuses(registry), name="status-watch")
        logger.info("watching %s for feeds (poll %.3fs)", feeds_path, poll)
        try:
            yield
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            await tailer.stop()

    app = FastAPI(title="noScribe Live", lifespan=lifespan)
    if token:
        app.add_middleware(TokenGate, token=token)
    app.state.registry = registry
    app.state.tailer = tailer

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "feeds_dir": str(feeds_path), "runs": len(registry)}

    @app.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        return registry.summaries()

    @app.get("/api/stream")
    async def stream(request: Request, run: str = "latest") -> StreamingResponse:
        # Proxy-friendly: no-transform stops a tunnel (e.g. Cloudflare) from rewriting the body, and
        # X-Accel-Buffering: no stops nginx from buffering it. Do not add compression middleware (GZipMiddleware)
        # over this route: a compressed SSE body is held back until the compressor flushes.
        return StreamingResponse(
            _sse_messages(request, registry, run or "latest"),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/peaks")
    async def run_peaks(run_id: str, n: int = Query(1200, ge=1, le=10000)) -> Response:
        run = registry.get(run_id)
        audio = run.audio_file if run is not None else None
        if not audio:
            return JSONResponse(
                {"error": f"unknown run, or its run_start has no audio_file: {run_id}"}, status_code=404
            )
        path = Path(audio)
        try:
            if not path.is_file():
                raise FileNotFoundError(audio)
            mtime = path.stat().st_mtime
        except OSError:
            return JSONResponse({"error": "audio file not found", "audio_file": audio}, status_code=404)

        key = (str(path), mtime, n)
        cached = peaks_cache.get(key)
        if cached is None:
            started = time.perf_counter()
            try:
                duration, peaks = await asyncio.to_thread(compute_peaks, path, n)
            except AudioDecodeError as exc:  # the file exists but ffprobe or ffmpeg cannot read audio from it
                logger.warning("peaks for run=%s: audio could not be decoded: %s", run_id, exc)
                return JSONResponse({"error": "audio could not be decoded", "detail": str(exc)}, status_code=422)
            except Exception as exc:  # a server failure, such as ffmpeg missing
                logger.warning("peaks for run=%s failed: %s", run_id, exc)
                return JSONResponse({"error": f"could not compute peaks: {exc}"}, status_code=500)
            logger.info("peaks run=%s n=%d computed in %.2fs", run_id, n, time.perf_counter() - started)
            cached = {"duration": duration, "peaks": peaks}
            peaks_cache[key] = cached
            while len(peaks_cache) > PEAKS_CACHE_MAX:
                peaks_cache.popitem(last=False)
        return JSONResponse({"run_id": run_id, "duration": cached["duration"], "n": n, "peaks": cached["peaks"]})

    def frontend(full_path: str) -> Response:
        """Serve the built frontend, with index.html as the fallback for unknown paths."""
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        index = static_path / "index.html"
        if not index.is_file():
            return HTMLResponse(PLACEHOLDER_HTML)
        root = static_path.resolve()
        try:
            candidate = (root / full_path).resolve() if full_path else root
            if candidate != root and candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
        except (OSError, ValueError):  # e.g. an embedded NUL byte in the path
            pass
        return FileResponse(index)

    @app.get("/", include_in_schema=False)
    async def frontend_root() -> Response:
        return frontend("")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_path(full_path: str) -> Response:
        return frontend(full_path)

    return app
