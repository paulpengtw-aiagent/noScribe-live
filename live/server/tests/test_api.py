"""HTTP tests for GET /api/runs/{id}/peaks: bad audio is a 422 with a short reason, never a 500.

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

import json
import os
import random
import shutil
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from server import peaks
from server.app import create_app


def make_client(tmp_path: Path):
    app = create_app(tmp_path / "feeds", tmp_path / "static")
    return TestClient(app), app.state.registry


def add_run(registry, run_id: str, audio: Path) -> None:
    event = {"v": 1, "type": "run_start", "t": time.time(), "seq": 0, "run_id": run_id, "audio_file": str(audio)}
    registry.ingest(event, server_t=time.time())


def write_tone(path: Path) -> bytes:
    rate = 8000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 32767).astype("<i2").tobytes())
    return path.read_bytes()


def test_unknown_run_is_404(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.get("/api/runs/nope/peaks")
    assert resp.status_code == 404
    assert "unknown run" in resp.json()["error"]


def test_missing_audio_file_is_404(tmp_path):
    client, registry = make_client(tmp_path)
    add_run(registry, "gone", tmp_path / "gone.mp3")
    resp = client.get("/api/runs/gone/peaks")
    assert resp.status_code == 404
    assert resp.json()["error"] == "audio file not found"


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
@pytest.mark.parametrize(
    "name, content",
    [
        ("empty.mp3", b""),
        ("random.mp3", random.Random(7).randbytes(4096)),
        ("truncated.wav", b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"),   # a header cut short
    ],
)
def test_undecodable_audio_is_422_with_a_short_reason_and_no_paths(tmp_path, name, content):
    audio = tmp_path / name
    audio.write_bytes(content)
    client, registry = make_client(tmp_path)
    add_run(registry, "bad", audio)
    resp = client.get("/api/runs/bad/peaks")
    body = resp.json()
    assert resp.status_code == 422
    assert body["error"] == "audio could not be decoded"
    assert isinstance(body["detail"], str) and 0 < len(body["detail"]) <= 200
    assert str(tmp_path) not in json.dumps(body)


@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_failed_decode_is_not_cached_so_a_fixed_file_is_read_again(tmp_path):
    audio = tmp_path / "fixed.wav"
    audio.write_bytes(b"")
    client, registry = make_client(tmp_path)
    add_run(registry, "fix", audio)
    assert client.get("/api/runs/fix/peaks").status_code == 422

    wav = write_tone(tmp_path / "tone.wav")
    audio.write_bytes(wav)
    later = time.time() + 10
    os.utime(audio, (later, later))
    resp = client.get("/api/runs/fix/peaks?n=20")
    assert resp.status_code == 200
    assert resp.json()["n"] == 20 and len(resp.json()["peaks"]) == 20


@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_decodable_file_still_returns_peaks(tmp_path):
    audio = tmp_path / "tone.wav"
    write_tone(audio)
    client, registry = make_client(tmp_path)
    add_run(registry, "ok", audio)
    resp = client.get("/api/runs/ok/peaks?n=10")
    assert resp.status_code == 200
    assert resp.json()["duration"] == pytest.approx(1.0, abs=0.05)


def test_a_server_failure_such_as_a_missing_ffmpeg_stays_a_500(tmp_path, monkeypatch):
    audio = tmp_path / "tone.wav"
    audio.write_bytes(b"not really audio, but the file exists")
    client, registry = make_client(tmp_path)
    add_run(registry, "srv", audio)

    def missing(tool: str) -> None:
        raise RuntimeError(f"{tool} is not installed or not on PATH")

    monkeypatch.setattr(peaks, "_require", missing)
    resp = client.get("/api/runs/srv/peaks")
    assert resp.status_code == 500
    assert "not installed" in resp.json()["error"]
