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
        opening = [await stream.__anext__() for _ in range(3)]    # retry, hello, snapshot
        monkeypatch.setattr(feed, "pid_alive", lambda pid: False)  # the CLI was killed
        assert registry.check_status_changes() is True
        message = await asyncio.wait_for(stream.__anext__(), timeout=5)
        await stream.aclose()
        return opening, message

    opening, message = asyncio.run(scenario())
    assert '"status": "running"' in opening[1]
    assert message.startswith("event: runs\n")
    assert '"status": "stale"' in message
