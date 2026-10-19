"""Tests for noScribe.live_feed, the opt-in NDJSON live feed.

Stdlib and pytest only. Nothing here needs the models, tkinter or PyAV.
"""
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The bare `pytest` entry point does not put the repo root on sys.path, and
# --noconftest skips the shared conftest, so make the package importable here.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from noScribe import live_feed  # noqa: E402

ENV = live_feed.ENV_VAR


@pytest.fixture(autouse=True)
def _no_target(monkeypatch):
    """Every test starts with no --live-feed override and no environment variable."""
    monkeypatch.delenv(ENV, raising=False)
    live_feed.configure(None)
    live_feed._issued_run_ids.clear()
    yield
    live_feed.configure(None)
    live_feed._issued_run_ids.clear()


def make_job(tmp_path, name="Interview 01.mp3", **overrides):
    values = dict(
        audio_file=str(tmp_path / name),
        transcript_file=str(tmp_path / "out" / "Interview 01.html"),
        language_name="German",
        speaker_detection="auto",
        overlapping=True,
        timestamps=False,
        disfluencies=False,
        pause=1,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def read_events(path):
    text = Path(path).read_text(encoding="utf-8")
    assert text.endswith("\n") or text == ""
    return [json.loads(line) for line in text.splitlines()]


def test_disabled_without_flag_or_env_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.phase("converting")
    feed.progress("transcribing", 50)
    feed.audio(3.0, 0.0)
    feed.diarization([{"start": 0, "end": 1000, "label": "SPEAKER_00"}])
    feed.model_ready("cpu", None, "int8", 1.0)
    feed.language("de", None)
    feed.segment(0, 0.0, 1.0, "S00", " Hallo")
    feed.end("finished", output_file=str(tmp_path / "out.html"))
    assert feed.run_id is None
    assert list(tmp_path.iterdir()) == []


def test_empty_flag_disables_even_when_env_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path / "from_env") + os.sep)
    live_feed.configure("")
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.end("finished")
    assert list(tmp_path.iterdir()) == []


def test_env_var_enables_feed_in_directory_mode(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path / "from_env") + os.sep)
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.end("finished")
    files = list((tmp_path / "from_env").iterdir())
    assert [p.name for p in files] == [f"{feed.run_id}.ndjson"]


def test_flag_wins_over_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path / "from_env.ndjson"))
    live_feed.configure(str(tmp_path / "from_flag.ndjson"))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.end("finished")
    assert not (tmp_path / "from_env.ndjson").exists()
    assert [e["type"] for e in read_events(tmp_path / "from_flag.ndjson")] == ["run_start", "run_end"]


def test_directory_mode_writes_run_start_first_with_increasing_seq(tmp_path):
    feed_dir = tmp_path / "feeds"
    live_feed.configure(str(feed_dir) + os.sep)
    job = make_job(tmp_path)
    feed = live_feed.open_job(job, "precise", noscribe_version="0.8")
    feed.phase("transcribing")
    feed.segment(0, 1.0, 2.0, "S00", " Hallo")
    feed.end("finished", output_file=str(tmp_path / "out.html"))

    files = list(feed_dir.iterdir())
    assert [p.name for p in files] == [f"{feed.run_id}.ndjson"]
    assert re.fullmatch(r"\d{8}-\d{6}-Interview_01", feed.run_id)

    events = read_events(files[0])
    assert [e["type"] for e in events] == ["run_start", "phase", "segment", "run_end"]
    assert [e["seq"] for e in events] == [0, 1, 2, 3]
    assert {e["run_id"] for e in events} == {feed.run_id}
    assert all(e["v"] == 1 for e in events)
    assert all(isinstance(e["t"], float) for e in events)

    start = events[0]
    assert start["audio_file"] == os.path.abspath(job.audio_file)
    assert start["output_file"] == os.path.abspath(job.transcript_file)
    assert start["model"] == "precise"
    assert start["language"] == "German"
    assert start["speaker_detection"] == "auto"
    assert start["options"] == {"overlapping": True, "timestamps": False,
                                "disfluencies": False, "pause": 1}
    assert start["pid"] == os.getpid()
    assert start["noscribe_version"] == "0.8"


def test_directory_mode_adds_suffix_when_run_id_is_taken(monkeypatch, tmp_path):
    monkeypatch.setattr(live_feed, "_timestamp", lambda: "20260101-120000")
    feed_dir = tmp_path / "feeds"
    live_feed.configure(str(feed_dir) + "/")
    feeds = [live_feed.open_job(make_job(tmp_path), "precise") for _ in range(3)]
    ids = [f.run_id for f in feeds]
    assert ids == ["20260101-120000-Interview_01",
                   "20260101-120000-Interview_01-2",
                   "20260101-120000-Interview_01-3"]
    assert sorted(p.name for p in feed_dir.iterdir()) == sorted(f"{i}.ndjson" for i in ids)
    for feed in feeds:
        feed.end("canceled")


def test_file_mode_appends_two_runs_each_with_its_own_run_start(tmp_path):
    target = tmp_path / "logs" / "feed.ndjson"
    live_feed.configure(str(target))
    first = live_feed.open_job(make_job(tmp_path), "precise")
    first.segment(0, 0.0, 1.0, "", " One")
    first.end("finished", output_file=str(tmp_path / "out.html"))
    second = live_feed.open_job(make_job(tmp_path, name="other.wav"), "breeze")
    second.end("error", error="boom")

    events = read_events(target)
    assert [e["type"] for e in events] == [
        "run_start", "segment", "run_end", "run_start", "run_end"]
    assert [e["run_id"] for e in events[:3]] == [first.run_id] * 3
    assert [e["run_id"] for e in events[3:]] == [second.run_id] * 2
    assert [e["seq"] for e in events] == [0, 1, 2, 0, 1]
    assert events[2]["status"] == "finished"
    assert events[4]["status"] == "error"
    assert events[4]["error"] == "boom"


def test_file_mode_keeps_run_ids_distinct_within_one_second(monkeypatch, tmp_path):
    monkeypatch.setattr(live_feed, "_timestamp", lambda: "20260101-120000")
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    first = live_feed.open_job(make_job(tmp_path), "precise")
    second = live_feed.open_job(make_job(tmp_path), "precise")
    first.end("canceled")
    second.end("canceled")
    assert first.run_id == "20260101-120000-Interview_01"
    assert second.run_id == "20260101-120000-Interview_01-2"
    assert {e["run_id"] for e in read_events(target)} == {first.run_id, second.run_id}


def test_progress_is_throttled_by_phase_detail_and_whole_percent(tmp_path):
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.progress("transcribing", 10.0)
    feed.progress("transcribing", 10.4)       # same whole percent: skipped
    feed.progress("transcribing", 10.9)       # same whole percent: skipped
    feed.progress("transcribing", 11.0)       # new whole percent: written
    feed.progress("diarizing", 11.2)          # other phase: written
    feed.progress("diarizing", 11.3, detail="embeddings")   # other detail: written
    feed.progress("diarizing", 11.4, detail="embeddings")   # same as last: skipped
    feed.end("finished")

    progress = [e for e in read_events(target) if e["type"] == "progress"]
    assert [(e["phase"], e["pct"], e["detail"]) for e in progress] == [
        ("transcribing", 10.0, None),
        ("transcribing", 11.0, None),
        ("diarizing", 11.2, None),
        ("diarizing", 11.3, "embeddings"),
    ]


def test_progress_is_clamped_to_0_100_and_rounded_to_one_decimal(tmp_path):
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.progress("a", 150.0)
    feed.progress("b", -3)
    feed.progress("c", 33.456)
    feed.progress("d", float("nan"))          # not a number: nothing written
    feed.end("finished")
    progress = [e for e in read_events(target) if e["type"] == "progress"]
    assert [e["pct"] for e in progress] == [100.0, 0.0, 33.5]


def test_end_writes_run_end_once_and_ignores_later_calls(tmp_path):
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.end("finished", output_file=str(tmp_path / "out.html"))
    feed.end("error", error="late")
    feed.segment(0, 0.0, 1.0, "", "late")
    events = read_events(target)
    assert [e["type"] for e in events] == ["run_start", "run_end"]
    end = events[1]
    assert end["status"] == "finished"
    assert end["error"] is None
    assert end["output_file"] == str(tmp_path / "out.html")
    assert isinstance(end["elapsed"], float)
    assert end["elapsed"] == round(end["elapsed"], 2)


def test_event_shapes_for_each_method(tmp_path):
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.phase("diarizing")
    feed.audio(61.5, 0.25)
    feed.diarization([
        {"start": 0, "end": 1000, "label": "SPEAKER_10"},
        {"start": 1000, "end": 2000, "label": "SPEAKER_01"},
        {"start": 2000, "end": 3000, "label": "SPEAKER_01"},
    ])
    feed.model_ready("cuda", "NVIDIA RTX", "float16", 3.14159)
    feed.language("de", 0.9876)
    feed.language("en", None)
    feed.segment(0, 1.25, 2.5, "//S01", " Hallo, Welt  ")
    feed.end("finished")
    events = {e["type"]: e for e in read_events(target)}
    assert events["phase"]["phase"] == "diarizing"
    assert events["audio"]["duration"] == 61.5
    assert events["audio"]["start_offset"] == 0.25
    assert events["diarization"]["speakers"] == ["S01", "S10"]
    assert events["diarization"]["turns"] == 3
    assert events["model_ready"]["component"] == "whisper"
    assert events["model_ready"]["device"] == "cuda"
    assert events["model_ready"]["device_name"] == "NVIDIA RTX"
    assert events["model_ready"]["compute_type"] == "float16"
    assert events["model_ready"]["load_seconds"] == 3.14
    languages = [e for e in read_events(target) if e["type"] == "language"]
    assert [(e["language"], e["probability"]) for e in languages] == [
        ("de", 0.9876), ("en", None)]
    segment = events["segment"]
    assert segment["index"] == 0
    assert segment["start"] == 1.25
    assert segment["end"] == 2.5
    assert segment["speaker"] == "//S01"
    assert segment["text"] == " Hallo, Welt  "


def test_non_ascii_is_written_as_is_not_escaped(tmp_path):
    target = tmp_path / "feed.ndjson"
    live_feed.configure(str(target))
    feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.segment(0, 0.0, 1.0, "", "你好世界")
    feed.end("finished")
    assert "你好世界" in target.read_text(encoding="utf-8")


def test_cjk_audio_name_is_kept_in_run_id(tmp_path):
    live_feed.configure(str(tmp_path / "feeds") + os.sep)
    feed = live_feed.open_job(make_job(tmp_path, name="會議 錄音.wav"), "precise")
    feed.end("finished")
    assert feed.run_id.endswith("-會議_錄音")


def test_run_id_base_sanitizes_and_truncates_the_stem():
    base = live_feed._run_id_base("dir/a:b c\\d  e\tf.mp3")
    assert base.endswith("-a_b_c_d_e_f")
    long_base = live_feed._run_id_base("x y" * 40 + ".wav")
    stem = long_base.split("-", 2)[2]
    assert len(stem) == 60
    assert "  " not in stem and " " not in stem


def test_write_failures_never_raise_and_are_logged_once(caplog):
    class BrokenHandle:
        def write(self, text):
            raise OSError("disk full")

        def flush(self):
            raise OSError("disk full")

        def close(self):
            raise OSError("disk full")

    feed = live_feed.JobFeed("run-x", BrokenHandle())
    with caplog.at_level(logging.WARNING, logger="noScribe.live_feed"):
        feed.phase("converting")
        feed.progress("transcribing", 5)
        feed.segment(0, 0.0, 1.0, "", "hi")
        feed.end("finished")
        feed.phase("late")
    warnings = [r for r in caplog.records if r.name == "noScribe.live_feed"]
    assert len(warnings) == 1
    assert "disk full" in warnings[0].getMessage()


def test_unopenable_target_gives_a_silent_noop_feed(tmp_path, caplog):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    live_feed.configure(str(blocker / "feed.ndjson"))
    with caplog.at_level(logging.WARNING, logger="noScribe.live_feed"):
        feed = live_feed.open_job(make_job(tmp_path), "precise")
    feed.phase("converting")
    feed.end("finished")
    assert blocker.read_text(encoding="utf-8") == "x"
    assert any("could not be opened" in r.getMessage() for r in caplog.records)


def test_importing_the_module_loads_no_heavy_libraries():
    code = (
        "import sys\n"
        "from noScribe import live_feed\n"
        "heavy = [m for m in ('tkinter', 'torch', 'av', 'numpy', 'customtkinter', 'faster_whisper')"
        " if m in sys.modules]\n"
        "print(heavy)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", code], env=env,
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
