"""Stream-level test: a run going stale reaches an open /api/stream as a ``runs`` message.

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

import asyncio
import time

from server import feed
from server.app import _sse_messages
from server.feed import RunRegistry


class _Connected:
    """Stands in for the starlette Request: the client never disconnects."""

    async def is_disconnected(self) -> bool:
        return False


def _run_start(run_id: str, t: float) -> dict:
    return {"v": 1, "type": "run_start", "t": t, "seq": 0, "run_id": run_id,
            "audio_file": "/media/interview.mp3", "pid": 4242}


def test_a_status_change_reaches_an_open_stream_as_a_runs_message(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: True)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(_run_start("job", now - 60), server_t=now)
    registry.check_status_changes()                     # baseline: running

    async def scenario():
        stream = _sse_messages(_Connected(), registry, "latest")
        opening = [await stream.__anext__() for _ in range(4)]    # retry, padding, hello, snapshot
        monkeypatch.setattr(feed, "pid_alive", lambda pid: False)  # the CLI was killed
        assert registry.check_status_changes() is True
        message = await asyncio.wait_for(stream.__anext__(), timeout=5)
        await stream.aclose()
        return opening, message

    opening, message = asyncio.run(scenario())
    assert '"status": "running"' in opening[2]
    assert message.startswith("event: runs\n")
    assert '"status": "stale"' in message


def _run_end(run_id: str, t: float) -> dict:
    return {"v": 1, "type": "run_end", "t": t, "seq": 9, "run_id": run_id,
            "status": "finished", "error": None, "output_file": None, "elapsed": 1.0}


def test_latest_stream_switches_to_an_older_live_run_when_the_newest_run_ends(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: True)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(_run_start("A", now - 100), server_t=now)     # older, still running
    registry.ingest(_run_start("B", now - 50), server_t=now)       # newest: what "latest" follows

    async def scenario():
        stream = _sse_messages(_Connected(), registry, "latest")
        opening = [await stream.__anext__() for _ in range(4)]
        registry.ingest(_run_end("B", now - 40), server_t=now)    # B ends
        messages = [await asyncio.wait_for(stream.__anext__(), timeout=5) for _ in range(2)]
        await stream.aclose()
        return opening, messages

    opening, (runs_message, snapshot_message) = asyncio.run(scenario())
    assert '"run_id": "B"' in opening[3]
    assert runs_message.startswith("event: runs\n")
    assert snapshot_message.startswith("event: snapshot\n")
    assert '"run_id": "A"' in snapshot_message


def test_latest_stream_switches_when_the_status_watcher_marks_the_newest_run_stale(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: True)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(_run_start("A", now - 100), server_t=now)     # pid 4242
    killed = _run_start("B", now - 50)
    killed["pid"] = 5151
    registry.ingest(killed, server_t=now)
    registry.check_status_changes()                               # baseline: both running

    async def scenario():
        stream = _sse_messages(_Connected(), registry, "latest")
        opening = [await stream.__anext__() for _ in range(4)]
        monkeypatch.setattr(feed, "pid_alive", lambda pid: pid != 5151)   # B's CLI was killed
        assert registry.check_status_changes() is True                    # the watcher's publish
        messages = [await asyncio.wait_for(stream.__anext__(), timeout=5) for _ in range(2)]
        await stream.aclose()
        return opening, messages

    opening, (runs_message, snapshot_message) = asyncio.run(scenario())
    assert '"run_id": "B"' in opening[3]
    assert runs_message.startswith("event: runs\n")
    assert '"run_id": "A"' in snapshot_message
