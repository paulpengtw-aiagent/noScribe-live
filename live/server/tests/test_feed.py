"""Tests for feed tailing, the run registry, waveform peaks and replay.

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from server import feed
from server.feed import STALE_AFTER_S, FeedTailer, RunRegistry
from server.peaks import compute_peaks
from server.replay import replay_events


# ---- helpers -----------------------------------------------------------------

def make_event(run_id: str, kind: str, t: float, seq: int = 0, **fields) -> dict:
    return {"v": 1, "type": kind, "t": t, "seq": seq, "run_id": run_id, **fields}


def start(run_id: str, t: float, audio: str = "/media/interview.mp3") -> dict:
    return make_event(
        run_id, "run_start", t,
        audio_file=audio, output_file="/out/interview.html", model="breeze-asr-25",
        language="Auto", speaker_detection="auto", options={"timestamps": True},
        pid=4242, noscribe_version="test",
    )


def segment(run_id: str, index: int, t: float) -> dict:
    return make_event(
        run_id, "segment", t, seq=index + 10, index=index,
        start=index * 3.0, end=index * 3.0 + 2.5, speaker="S00", text=f"segment {index}",
    )


def end(run_id: str, t: float, status: str = "finished") -> dict:
    return make_event(run_id, "run_end", t, status=status, error=None, output_file="/out/interview.html", elapsed=12.5)


def as_line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def make_tailer(feeds: Path) -> tuple[FeedTailer, RunRegistry]:
    registry = RunRegistry()
    return FeedTailer(feeds, 0.05, registry), registry


# ---- feed tailing -------------------------------------------------------------

def test_partial_line_is_held_until_its_newline_arrives(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    feed = tmp_path / "job-1.ndjson"
    data = as_line(start("job-1", 100.0))

    feed.write_bytes(data[:25])            # the CLI is mid-write
    assert tailer.scan_once() == 0
    assert registry.get("job-1") is None

    with feed.open("ab") as fh:
        fh.write(data[25:-1])              # everything except the newline
    assert tailer.scan_once() == 0

    with feed.open("ab") as fh:
        fh.write(b"\n")
    assert tailer.scan_once() == 1
    run = registry.get("job-1")
    assert run is not None and run.started_t == 100.0
    assert registry.summaries()[0]["audio_name"] == "interview.mp3"


def test_several_partial_writes_with_segments_between_them(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    feed = tmp_path / "job.ndjson"
    blob = as_line(start("job", 1.0)) + as_line(segment("job", 0, 2.0)) + as_line(segment("job", 1, 3.0))
    ingested = 0
    for cut in range(0, len(blob), 17):   # append in 17-byte pieces, polling after each
        with feed.open("ab") as fh:
            fh.write(blob[cut:cut + 17])
        ingested += tailer.scan_once()
    assert ingested == 3
    assert registry.get("job").segments == 2
    assert [e["type"] for e in registry.get("job").events] == ["run_start", "segment", "segment"]


def test_several_runs_in_one_file_are_split_by_run_id(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    events = [
        start("a", 100.0), segment("a", 0, 101.0), segment("a", 1, 102.0), end("a", 103.0),
        start("b", 200.0), segment("b", 0, 201.0), end("b", 202.0, status="error"),
    ]
    (tmp_path / "job.ndjson").write_bytes(b"".join(as_line(e) for e in events))

    assert tailer.scan_once() == len(events)
    a, b = registry.get("a"), registry.get("b")
    assert [e["type"] for e in a.events] == ["run_start", "segment", "segment", "run_end"]
    assert [e["type"] for e in b.events] == ["run_start", "segment", "run_end"]
    assert (a.status, b.status) == ("finished", "error")
    assert (a.segments, b.segments) == (2, 1)
    assert all("server_t" in e for e in a.events + b.events)


def test_latest_run_follows_the_newest_run_start(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    (tmp_path / "first.ndjson").write_bytes(as_line(start("first", 100.0)))
    tailer.scan_once()
    assert registry.latest_run_id == "first"

    (tmp_path / "second.ndjson").write_bytes(as_line(start("second", 200.0)) + as_line(segment("second", 0, 201.0)))
    tailer.scan_once()
    assert registry.latest_run_id == "second"

    # A run that started earlier does not take the lead back.
    (tmp_path / "older.ndjson").write_bytes(as_line(start("older", 50.0)))
    tailer.scan_once()
    assert registry.latest_run_id == "second"


def test_truncated_file_is_read_again_from_the_start(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    feed = tmp_path / "job.ndjson"
    feed.write_bytes(as_line(start("job", 1.0)) + as_line(segment("job", 0, 2.0)) + as_line(segment("job", 1, 3.0)))
    assert tailer.scan_once() == 3
    assert registry.get("job").segments == 2

    # Rewrite in place with less data than was already consumed (same inode).
    feed.write_bytes(as_line(start("job", 10.0)) + as_line(segment("job", 0, 11.0)))
    assert tailer.scan_once() == 2
    run = registry.get("job")
    assert run.started_t == 10.0 and run.segments == 1


def test_replaced_file_is_read_again_from_the_start(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    feed = tmp_path / "job.ndjson"
    feed.write_bytes(as_line(start("job", 1.0)) + as_line(segment("job", 0, 2.0)))
    tailer.scan_once()

    fresh = tmp_path / "job.ndjson.tmp"          # not matched by *.ndjson
    fresh.write_bytes(as_line(start("job", 5.0)) + as_line(segment("job", 0, 6.0)) + as_line(segment("job", 1, 7.0)))
    os.replace(fresh, feed)                      # new inode under the same name
    tailer.scan_once()
    run = registry.get("job")
    assert run.started_t == 5.0 and run.segments == 2


def test_unparseable_and_runless_lines_are_skipped_with_a_warning(tmp_path, caplog):
    tailer, registry = make_tailer(tmp_path)
    blob = (
        b'{"run_id": "job", "type": "run_start"\n'      # truncated JSON
        + b"[1, 2, 3]\n"                                 # valid JSON, not an object
        + as_line({"type": "segment", "t": 1.0})         # no run_id
        + as_line(start("job", 2.0))
        + b"\xff\xfe garbage\n"                          # not UTF-8
    )
    (tmp_path / "job.ndjson").write_bytes(blob)
    with caplog.at_level(logging.WARNING, logger="server.feed"):
        assert tailer.scan_once() == 1
    assert registry.get("job").started_t == 2.0
    assert "unparseable" in caplog.text
    assert "without run_id" in caplog.text


def test_startup_loads_only_the_30_most_recent_files(tmp_path):
    for i in range(32):
        name = f"run-{i:02d}"
        path = tmp_path / f"{name}.ndjson"
        path.write_bytes(as_line(start(name, 1000.0 + i)))
        os.utime(path, (1_000_000 + i, 1_000_000 + i))   # run-31 is the newest
    tailer, registry = make_tailer(tmp_path)

    assert tailer.scan_once() == 30
    assert registry.get("run-00") is None and registry.get("run-01") is None
    assert registry.get("run-02") is not None and registry.get("run-31") is not None

    # Old files are followed from their current end: appended lines are picked up,
    # but their existing content is not loaded.
    with (tmp_path / "run-00.ndjson").open("ab") as fh:
        fh.write(as_line(segment("run-00", 0, 9.0)))
    assert tailer.scan_once() == 1
    assert registry.get("run-00").segments == 1


def test_subscribers_get_every_event_in_order(tmp_path):
    tailer, registry = make_tailer(tmp_path)
    queue = registry.subscribe()
    (tmp_path / "job.ndjson").write_bytes(as_line(start("job", 1.0)) + as_line(segment("job", 0, 2.0)))
    tailer.scan_once()

    received = []
    while not queue.empty():
        kind, run_id, payload = queue.get_nowait()
        received.append((kind, run_id, payload["type"]))
    assert received == [("event", "job", "run_start"), ("event", "job", "segment")]
    registry.unsubscribe(queue)


def test_a_subscriber_that_falls_behind_is_dropped_with_a_marker(monkeypatch):
    monkeypatch.setattr("server.feed.SUBSCRIBER_QUEUE_MAX", 3)
    registry = RunRegistry()
    queue = registry.subscribe()
    for i in range(4):   # the fourth event overflows a queue of size 3
        registry.ingest(make_event("job", "phase", float(i), phase="transcribing"))

    kind, run_id, payload = queue.get_nowait()
    assert (kind, run_id, payload) == ("dropped", None, None)
    assert queue.empty()
    registry.ingest(make_event("job", "phase", 9.0, phase="transcribing"))   # no longer delivered here
    assert queue.empty()


# ---- run summaries --------------------------------------------------------------

def test_running_run_with_no_events_for_30_minutes_is_stale(tmp_path):
    registry = RunRegistry()
    now = time.time()
    registry.ingest(start("old", now - STALE_AFTER_S - 60), server_t=now)
    registry.ingest(start("live", now - 5), server_t=now)
    registry.ingest(start("done", now - STALE_AFTER_S - 60), server_t=now)
    registry.ingest(end("done", now - STALE_AFTER_S - 30), server_t=now)

    statuses = {s["run_id"]: s["status"] for s in registry.summaries(now=now)}
    assert statuses == {"old": "stale", "live": "running", "done": "finished"}


def test_summary_fields_come_from_the_events(tmp_path):
    registry = RunRegistry()
    events = [
        start("r", 100.0),
        make_event("r", "model_ready", 101.0, component="whisper", device="cuda", device_name="RTX", compute_type="float16", load_seconds=2.5),
        make_event("r", "audio", 101.5, duration=202.4, start_offset=0.0),
        make_event("r", "diarization", 110.0, speakers=["S00", "S01"], turns=12),
        segment("r", 0, 111.0),
        end("r", 130.0),
    ]
    for ev in events:
        registry.ingest(ev, server_t=ev["t"] + 0.01, feed_file=tmp_path / "r.ndjson")
    s = registry.summaries(now=131.0)[0]
    assert (s["status"], s["segments"], s["duration"], s["device"], s["device_name"]) == ("finished", 1, 202.4, "cuda", "RTX")
    assert (s["started_t"], s["ended_t"], s["last_t"]) == (100.0, 130.0, 130.0)
    assert s["speakers"] == ["S00", "S01"]
    assert s["feed_file"] == str(tmp_path / "r.ndjson")


def test_windows_style_audio_paths_give_a_name(tmp_path):
    registry = RunRegistry()
    registry.ingest(start("w", 1.0, audio=r"C:\Users\me\Interview 01.mp3"))
    assert registry.summaries()[0]["audio_name"] == "Interview 01.mp3"


# ---- waveform peaks -------------------------------------------------------------

@pytest.fixture(scope="session")
def sine_wav(tmp_path_factory) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    out = tmp_path_factory.mktemp("audio") / "sine.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(out)],
        check=True,
    )
    return out


def test_peaks_of_a_three_second_sine(sine_wav):
    duration, peaks = compute_peaks(sine_wav, 60)
    assert duration == pytest.approx(3.0, abs=0.05)
    assert len(peaks) == 60
    assert all(0.0 <= p <= 1.0 for p in peaks)
    assert min(peaks) > 0.9      # a constant tone is at the reference level everywhere


def test_peaks_follow_loudness_over_time(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    rate = 8000
    signal = np.zeros(rate * 2)                       # two seconds: silence, then a tone
    signal[rate:] = 0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    path = tmp_path / "half.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((signal * 32767).astype("<i2").tobytes())

    duration, peaks = compute_peaks(path, 20)
    assert duration == pytest.approx(2.0, abs=0.05)
    assert max(peaks[:9]) < 0.01                      # first half is silent
    assert min(peaks[11:]) > 0.9                      # second half is at the reference level


# ---- replay -----------------------------------------------------------------------

def test_replay_writes_a_new_run_with_new_ids_and_fresh_times(tmp_path):
    events = [start("orig/1", 100.0), segment("orig/1", 0, 101.0), end("orig/1", 102.0)]
    outputs = replay_events(events, tmp_path, speed=1000.0, max_gap=0.0, stamp="20260101-000000")

    assert len(outputs) == 1
    new_id, path, count = outputs[0]
    assert new_id == "replay-20260101-000000-orig_1"
    assert path == tmp_path / f"{new_id}.ndjson" and count == 3
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(e["run_id"] == new_id for e in lines)
    assert all(abs(e["t"] - time.time()) < 60 for e in lines)
    assert [e["type"] for e in lines] == ["run_start", "segment", "run_end"]
    assert lines[0]["pid"] == os.getpid()          # the replay process, alive while it replays
    assert all("pid" not in e for e in lines[1:])


# ---- liveness by pid ----------------------------------------------------------------

def test_pid_alive_sees_this_process_and_not_a_reaped_child():
    assert feed.pid_alive(os.getpid()) is True
    child = subprocess.Popen(["true"])
    child.wait()
    assert feed.pid_alive(child.pid) is False


@pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="the zombie check reads /proc")
def test_pid_alive_treats_an_unreaped_zombie_as_gone():
    child = subprocess.Popen(["true"])
    time.sleep(0.3)                       # it has exited, and stays a zombie until waited for
    try:
        assert feed.pid_alive(child.pid) is False
    finally:
        child.wait()


def test_a_run_whose_cli_is_gone_turns_stale_after_the_grace_period(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: False)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(start("killed", now - 10), server_t=now)      # pid 4242, last event 10 s ago
    assert registry.summaries(now=now)[0]["status"] == "stale"


def test_a_run_whose_cli_just_went_quiet_is_not_stale_yet(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: False)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(start("fresh", now - 2), server_t=now)
    assert registry.summaries(now=now)[0]["status"] == "running"


def test_a_live_cli_keeps_a_quiet_run_running(monkeypatch):
    checked = []
    monkeypatch.setattr(feed, "pid_alive", lambda pid: checked.append(pid) or True)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(start("quiet", now - 600), server_t=now)      # 10 minutes quiet, under the 30-minute rule
    assert registry.summaries(now=now)[0]["status"] == "running"
    assert checked == [4242]


def test_a_run_without_a_pid_only_goes_stale_by_the_30_minute_rule(monkeypatch):
    checked = []
    monkeypatch.setattr(feed, "pid_alive", lambda pid: checked.append(pid) or False)
    now = time.time()
    registry = RunRegistry()
    event = start("nopid", now - 600)
    del event["pid"]
    registry.ingest(event, server_t=now)
    assert registry.summaries(now=now)[0]["status"] == "running"
    assert checked == []


def test_check_status_changes_publishes_once_when_a_run_goes_stale(monkeypatch):
    monkeypatch.setattr(feed, "pid_alive", lambda pid: True)
    now = time.time()
    registry = RunRegistry()
    registry.ingest(start("job", now - 60), server_t=now)
    queue = registry.subscribe()
    assert registry.check_status_changes() is False     # the first check only records the statuses
    assert registry.check_status_changes() is False     # nothing changed

    monkeypatch.setattr(feed, "pid_alive", lambda pid: False)
    assert registry.check_status_changes() is True      # running -> stale
    assert registry.check_status_changes() is False     # already published

    assert queue.get_nowait() == ("runs", None, {})
    assert queue.empty()
