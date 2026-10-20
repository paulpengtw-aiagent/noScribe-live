"""Feed tailing and the run registry for noScribe Live.

The patched noScribe CLI appends NDJSON lines to ``<feeds dir>/<run_id>.ndjson``.
``FeedTailer`` polls that directory and parses only complete lines. Each event goes
to a ``RunRegistry``, which keeps the events of every run, a summary per run, and
pushes new events to subscriber queues (the SSE streams in ``app.py``).

This module does not import FastAPI. Everything runs on the asyncio event loop
thread, so the registry needs no locks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["FeedTailer", "Run", "RunRegistry", "drain_queue"]

logger = logging.getLogger("server.feed")

STALE_AFTER_S = 30 * 60        # a running run with no event for this long is reported as "stale"
DEAD_PID_GRACE_S = 5.0         # a running run whose CLI pid is gone and that has been quiet this long is "stale"
STARTUP_MAX_FILES = 30         # at startup only this many (most recently modified) feed files are read
READ_CHUNK = 1 << 20           # bytes read from one feed file per poll (bounds memory and loop time)
MAX_LINE_BYTES = 1 << 20       # longer lines are dropped; real events are a few hundred bytes
SUBSCRIBER_QUEUE_MAX = 10_000  # backlog allowed per subscriber before it is dropped
OUTPUT_CHECK_S = 2.0           # the isfile check of output_file is reused this long (summaries are built often)


def _num(value: Any) -> float | None:
    """Return ``value`` as a finite float, or None if it is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fmt(value: Any, spec: str) -> str:
    """Format a number with a format spec; anything that is not a number is printed as-is."""
    number = _num(value)
    return str(value) if number is None else format(number, spec)


def _basename(path: str) -> str:
    """Last component of a path. Accepts both / and \\ because the CLI may run on Windows."""
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def pid_alive(pid: int) -> bool:
    """True if a process with this pid exists. A zombie (exited, not yet reaped) counts as gone.

    Tests replace this function. On Windows, ``os.kill(pid, 0)`` would terminate the process,
    so there it answers True and the 30-minute rule alone applies.
    """
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:          # PermissionError: the process exists but belongs to someone else
        return True
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            stat_line = fh.read().decode("ascii", "replace")
    except OSError:          # no /proc (not Linux) or the process vanished: not a zombie as far as we know
        return False
    fields = stat_line.rsplit(")", 1)[-1].split()   # the state follows the command name in parentheses
    return bool(fields) and fields[0] == "Z"


def _pid(value: Any) -> int | None:
    """A usable process id, or None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def drain_queue(queue: asyncio.Queue) -> None:
    """Discard everything currently queued."""
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return


@dataclass
class Run:
    """One transcription run: its raw events plus a summary derived from them."""

    run_id: str
    feed_file: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)  # raw events, each with "server_t"
    status: str = "running"            # "running" until run_end, then its status (finished/error/canceled)
    error: str | None = None
    audio_file: str | None = None
    output_file: str | None = None
    model: str | None = None
    language: str | None = None
    detected_language: str | None = None
    speaker_detection: str | None = None
    speakers: list[str] | None = None
    phase: str | None = None
    pct: float | None = None
    duration: float | None = None      # seconds of audio, from the audio event
    device: str | None = None          # whisper device: "cuda" or "cpu"
    device_name: str | None = None
    segments: int = 0
    pid: int | None = None             # CLI process id from run_start; a dead pid means the CLI was killed
    started_t: float | None = None     # CLI wall-clock time of run_start (decides "latest")
    ended_t: float | None = None
    last_t: float | None = None        # CLI wall-clock time of the newest event
    _output_check: tuple[str, float, bool] | None = field(default=None, repr=False, compare=False)  # (path, checked at, exists)

    def apply(self, ev: dict[str, Any]) -> None:
        """Fold one event into the summary fields."""
        kind = ev.get("type")
        t = _num(ev.get("t"))
        if t is not None:
            self.last_t = t if self.last_t is None else max(self.last_t, t)

        if kind == "run_start":
            self.started_t = t
            self.status = "running"
            self.pid = _pid(ev.get("pid"))
            self.audio_file = ev.get("audio_file")
            self.output_file = ev.get("output_file")
            self.model = ev.get("model")
            self.language = ev.get("language")
            self.speaker_detection = ev.get("speaker_detection")
        elif kind == "phase":
            self.phase = ev.get("phase")
        elif kind == "progress":
            self.phase = ev.get("phase") or self.phase
            self.pct = _num(ev.get("pct"))
        elif kind == "audio":
            self.duration = _num(ev.get("duration"))
        elif kind == "diarization":
            speakers = ev.get("speakers")
            self.speakers = list(speakers) if isinstance(speakers, list) else None
        elif kind == "model_ready":
            if ev.get("component", "whisper") == "whisper":
                self.device = ev.get("device")
                self.device_name = ev.get("device_name")
        elif kind == "language":
            self.detected_language = ev.get("language")
        elif kind == "segment":
            self.segments += 1
        elif kind == "run_end":
            self.status = ev.get("status") or "finished"
            self.ended_t = t
            self.error = ev.get("error")
            self.output_file = ev.get("output_file") or self.output_file

    def effective_status(self, now: float) -> str:
        """The status viewers see. A running run is "stale" when its CLI is gone (the pid is dead and
        the run has been quiet for DEAD_PID_GRACE_S), or when it has been quiet for STALE_AFTER_S."""
        if self.status != "running" or self.last_t is None:
            return self.status
        idle = now - self.last_t
        if idle > STALE_AFTER_S:
            return "stale"
        if self.pid is not None and idle > DEAD_PID_GRACE_S and not pid_alive(self.pid):
            return "stale"
        return self.status

    def output_name(self, now: float) -> str | None:
        """Basename of output_file if that file exists, else None. The isfile check is reused for OUTPUT_CHECK_S."""
        path = self.output_file
        if not path:
            return None
        cached = self._output_check
        if cached is None or cached[0] != path or not 0 <= now - cached[1] < OUTPUT_CHECK_S:
            cached = (path, now, os.path.isfile(path))
            self._output_check = cached
        return _basename(path) if cached[2] else None

    def inferred_end_t(self, status: str) -> float | None:
        """When the run ended, as far as the viewer can tell: last_t for a stale run (its last event),
        ended_t for an ended run, and None while it is running."""
        if status == "running":
            return None
        return self.last_t if status == "stale" else self.ended_t

    def summary(self, now: float) -> dict[str, Any]:
        """JSON-ready summary, with the status from effective_status()."""
        status = self.effective_status(now)
        return {
            "run_id": self.run_id,
            "audio_name": _basename(self.audio_file) if self.audio_file else None,
            "audio_file": self.audio_file,
            "output_file": self.output_file,
            "output_name": self.output_name(now),
            "model": self.model,
            "language": self.language,
            "detected_language": self.detected_language,
            "speaker_detection": self.speaker_detection,
            "status": status,
            "live": status == "running",
            "inferred_end_t": self.inferred_end_t(status),
            "error": self.error,
            "started_t": self.started_t,
            "ended_t": self.ended_t,
            "last_t": self.last_t,
            "segments": self.segments,
            "duration": self.duration,
            "device": self.device,
            "device_name": self.device_name,
            "phase": self.phase,
            "pct": self.pct,
            "speakers": self.speakers,
            "feed_file": self.feed_file,
        }


class RunRegistry:
    """All runs seen so far, keyed by run_id, plus fan-out of new events to subscribers."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._last_statuses: dict[str, str] = {}   # run_id -> effective status seen by the last check

    def __len__(self) -> int:
        return len(self._runs)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    @property
    def latest_run_id(self) -> str | None:
        """The run that "latest" follows: the newest-started run whose effective status is "running".
        If none is running, the newest-started run. None if no run has started."""
        now = time.time()
        newest: Run | None = None
        newest_live: Run | None = None
        for run in self._runs.values():
            if run.started_t is None:
                continue
            if newest is None or run.started_t >= newest.started_t:
                newest = run
            if run.effective_status(now) == "running" and (newest_live is None or run.started_t >= newest_live.started_t):
                newest_live = run
        best = newest_live if newest_live is not None else newest
        return best.run_id if best is not None else None

    def summaries(self, now: float | None = None) -> list[dict[str, Any]]:
        """Summaries of all runs, newest first."""
        now = time.time() if now is None else now

        def newest_key(run: Run) -> float:
            if run.started_t is not None:
                return run.started_t
            return run.last_t if run.last_t is not None else 0.0

        return [run.summary(now) for run in sorted(self._runs.values(), key=newest_key, reverse=True)]

    def check_status_changes(self, now: float | None = None) -> bool:
        """Compare every run's effective status with the last check. If one changed (running -> stale,
        say), publish ``("runs", None, {})`` to all subscribers. Runs seen for the first time are
        recorded silently: their run_start already published a change. Returns True if it published."""
        now = time.time() if now is None else now
        statuses = {run.run_id: run.effective_status(now) for run in self._runs.values()}
        changed = any(self._last_statuses.get(run_id, status) != status for run_id, status in statuses.items())
        self._last_statuses = statuses
        if changed:
            self._publish(("runs", None, {}))
        return changed

    # ---- ingestion -------------------------------------------------------

    def ingest(
        self,
        event: dict[str, Any],
        server_t: float | None = None,
        feed_file: str | os.PathLike | None = None,
    ) -> dict[str, Any] | None:
        """Store one event under its run and notify subscribers. Returns the stored event, or None if skipped."""
        run_id = event.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            logger.warning("skipping event without run_id (type=%r)", event.get("type"))
            return None
        server_t = time.time() if server_t is None else server_t
        wrapped = dict(event)
        wrapped["server_t"] = server_t
        kind = event.get("type")

        run = self._runs.get(run_id)
        if kind == "run_start" and run is not None:
            # The same run_start again means its feed file was re-read: start the run over.
            logger.info("run_start for known run=%s; starting its state over", run_id)
            run = None
        if run is None:
            run = Run(run_id=run_id, feed_file=None if feed_file is None else str(feed_file))
            self._runs[run_id] = run
        run.events.append(wrapped)
        run.apply(wrapped)

        self._log(run_id, wrapped)
        self._broadcast(run_id, wrapped)
        return wrapped

    def _log(self, run_id: str, ev: dict[str, Any]) -> None:
        kind = ev.get("type")
        if kind == "segment":
            cli_t = _num(ev.get("t"))
            lag = "?" if cli_t is None else f"{(ev['server_t'] - cli_t) * 1000:.0f}"
            logger.info(
                "segment run=%s #%s media=%s-%ss cli_t=%s server_t=%.3f tail_lag_ms=%s",
                run_id,
                ev.get("index"),
                _fmt(ev.get("start"), ".2f"),
                _fmt(ev.get("end"), ".2f"),
                _fmt(cli_t, ".3f"),
                ev["server_t"],
                lag,
            )
        elif kind == "run_start":
            logger.info(
                "run_start run=%s audio=%s model=%s language=%s",
                run_id,
                _basename(str(ev.get("audio_file"))),
                ev.get("model"),
                ev.get("language"),
            )
        elif kind == "run_end":
            logger.info(
                "run_end run=%s status=%s elapsed=%s error=%s",
                run_id,
                ev.get("status"),
                ev.get("elapsed"),
                ev.get("error"),
            )

    # ---- subscribers -----------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Queue of ``(kind, run_id, payload)`` tuples. kind is "event" (payload = stored event) or "dropped"."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, run_id: str, wrapped: dict[str, Any]) -> None:
        self._publish(("event", run_id, wrapped))

    def _publish(self, item: tuple) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                # A client that falls this far behind is cut off. Its stream ends with a
                # "dropped" marker, and the browser reconnects and gets a fresh snapshot.
                logger.warning("subscriber fell %d events behind; dropping it", SUBSCRIBER_QUEUE_MAX)
                self._subscribers.discard(queue)
                drain_queue(queue)
                queue.put_nowait(("dropped", None, None))


@dataclass
class _FileState:
    """Read position within one feed file."""

    inode: int
    offset: int = 0            # bytes consumed so far
    buf: bytes = b""           # bytes after the last newline, i.e. an incomplete line
    discarding: bool = False   # True while skipping the rest of an over-long line


class FeedTailer:
    """Polls the feeds directory and feeds every complete line into a RunRegistry.

    The app calls ``start()`` inside the running event loop (from its lifespan) and
    ``await stop()`` on shutdown. ``scan_once()`` performs one poll synchronously;
    tests call it directly.
    """

    def __init__(
        self,
        feeds_dir: str | os.PathLike,
        poll: float = 0.05,
        registry: RunRegistry | None = None,
    ) -> None:
        self.feeds_dir = Path(feeds_dir)
        self.poll = poll
        self.registry = registry if registry is not None else RunRegistry()
        self._files: dict[str, _FileState] = {}   # keyed by str(path)
        self._first_scan = True
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run(), name="feed-tailer")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception:  # one bad scan must not stop tailing
                logger.exception("feed scan failed; will retry")
            await asyncio.sleep(self.poll)

    def scan_once(self) -> int:
        """Read whatever was appended since the last scan. Returns the number of events ingested."""
        self.feeds_dir.mkdir(parents=True, exist_ok=True)

        found: dict[str, tuple[Path, os.stat_result]] = {}
        for path in self.feeds_dir.glob("*.ndjson"):
            try:
                st = path.stat()
            except FileNotFoundError:  # removed since it was listed
                continue
            if stat.S_ISREG(st.st_mode):
                found[str(path)] = (path, st)
        for key in [k for k in self._files if k not in found]:
            del self._files[key]

        startup = self._first_scan
        self._first_scan = False
        recent: set[str] = set()
        if startup:
            by_mtime = sorted(found, key=lambda k: found[k][1].st_mtime, reverse=True)
            recent = set(by_mtime[:STARTUP_MAX_FILES])
            if len(found) > STARTUP_MAX_FILES:
                logger.info(
                    "startup: loading the %d most recent of %d feed files; older ones are followed "
                    "only from their current end",
                    STARTUP_MAX_FILES,
                    len(found),
                )

        ingested = 0
        for key, (path, st) in found.items():
            state = self._files.get(key)
            if state is None:
                # A file we have not seen before. At startup, old files are skipped (we start at
                # their current end); every other new file is read from the top.
                skip_old = startup and key not in recent
                state = _FileState(inode=st.st_ino, offset=st.st_size if skip_old else 0)
                self._files[key] = state
            elif st.st_ino != state.inode or st.st_size < state.offset:
                logger.info("feed file %s was replaced or truncated; reading it again from the start", path.name)
                state = _FileState(inode=st.st_ino)
                self._files[key] = state
            if st.st_size > state.offset:
                ingested += self._read_new(path, state, st.st_size)
        return ingested

    def _read_new(self, path: Path, state: _FileState, size: int) -> int:
        """Read up to READ_CHUNK new bytes and ingest the complete lines among them."""
        try:
            with path.open("rb") as fh:
                fh.seek(state.offset)
                data = fh.read(min(size - state.offset, READ_CHUNK))
        except FileNotFoundError:
            return 0
        state.offset += len(data)

        if state.discarding:
            newline = data.find(b"\n")
            if newline < 0:
                return 0  # still inside the over-long line
            data = data[newline + 1:]
            state.discarding = False

        # Everything after the final newline is an incomplete line: keep it for the next poll.
        *complete, rest = (state.buf + data).split(b"\n")
        if len(rest) > MAX_LINE_BYTES:
            logger.warning("discarding a line longer than %d bytes in %s", MAX_LINE_BYTES, path.name)
            state.discarding = True
            rest = b""
        state.buf = rest
        return sum(self._ingest_line(path, raw) for raw in complete)

    def _ingest_line(self, path: Path, raw: bytes) -> int:
        """Parse one complete line and hand it to the registry. Returns 1 if an event was stored."""
        text = raw.strip()
        if not text:
            return 0
        if len(text) > MAX_LINE_BYTES:
            logger.warning("skipping an over-long line in %s", path.name)
            return 0
        try:
            event = json.loads(text)  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        except ValueError as exc:
            logger.warning("skipping unparseable line in %s: %s: %r", path.name, exc, text[:120])
            return 0
        if not isinstance(event, dict):
            logger.warning("skipping non-object line in %s: %r", path.name, text[:120])
            return 0
        stored = self.registry.ingest(event, server_t=time.time(), feed_file=path)
        return 0 if stored is None else 1
