"""Opt-in live feed of a transcription, written as NDJSON (one JSON object per line).

Enabled with ``--live-feed PATH`` or the ``NOSCRIBE_LIVE_FEED`` environment
variable; the flag wins. Without a target every call here does nothing: no file
is created and nothing is printed.

The event format is documented in ``live/FEED.md``. This module is stdlib only,
and every ``JobFeed`` method swallows its own exceptions (the first one is logged
as a warning), so a feed problem can never change or stop a transcription.
"""

import functools
import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path

ENV_VAR = "NOSCRIBE_LIVE_FEED"
FORMAT_VERSION = 1

_log = logging.getLogger(__name__)

# Set by configure(). None means "not configured", so the environment decides.
_configured_target = None

# Run ids handed out in this process. File mode appends many runs to one file,
# so this is what keeps two runs started in the same second apart.
_issued_run_ids = set()
_issued_lock = threading.Lock()

_MAX_STEM_LENGTH = 60


def configure(path):
    """Set the feed target (the --live-feed flag). Overrides NOSCRIBE_LIVE_FEED.

    None forgets an earlier override. An empty string turns the feed off even
    when the environment variable is set.
    """
    global _configured_target
    _configured_target = None if path is None else str(path)


def _resolve_target():
    target = _configured_target
    if target is None:
        target = os.environ.get(ENV_VAR, "")
    return target if target.strip() else None


def _is_directory_target(target):
    return target.endswith(("/", os.sep)) or os.path.isdir(target)


def _numbered(base, n):
    return base if n == 1 else f"{base}-{n}"


def _timestamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _run_id_base(audio_file):
    stem = Path(str(audio_file or "")).stem
    clean = re.sub(r"_+", "_", re.sub(r"[^\w.-]", "_", stem))[:_MAX_STEM_LENGTH]
    return f"{_timestamp()}-{clean or 'job'}"


def _create_in_directory(directory, base):
    """Create <directory>/<run_id>.ndjson exclusively and return (run_id, handle).

    "x" mode makes the name claim atomic, so a clash with an existing file (or
    with another process) moves on to the next -2, -3, ... suffix.
    """
    n = 1
    while True:
        run_id = _numbered(base, n)
        try:
            handle = open(directory / f"{run_id}.ndjson", "x",
                          encoding="utf-8", newline="\n", buffering=1)
        except FileExistsError:
            n += 1
            continue
        return run_id, handle


def _reserve_run_id(base):
    with _issued_lock:
        n = 1
        while _numbered(base, n) in _issued_run_ids:
            n += 1
        run_id = _numbered(base, n)
        _issued_run_ids.add(run_id)
        return run_id


def _num(value, ndigits=None):
    """A finite float for JSON, or None: NaN and infinity are not valid JSON."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, ndigits) if ndigits is not None else number


def _text(value):
    return None if value is None else str(value)


def _plain(value):
    """Keep JSON scalars as they are, and turn anything else into text."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _abspath(value):
    return None if value is None else os.path.abspath(str(value))


def _guarded(method):
    """Turn any exception raised by a JobFeed method into a single logged warning."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self._warn(exc)
            return None
    return wrapper


class JobFeed:
    """Writes the events of one transcription job. A disabled feed does nothing."""

    def __init__(self, run_id=None, handle=None):
        self.run_id = run_id
        self._handle = handle
        self._closed = handle is None
        self._seq = 0
        self._started = time.monotonic()
        self._last_progress = None
        self._warned = False
        self._lock = threading.Lock()

    @classmethod
    def disabled(cls):
        """A feed that ignores every call and touches nothing."""
        return cls()

    def _warn(self, exc):
        if self._warned:
            return
        self._warned = True
        _log.warning("live feed error in run %s (later errors in this run are not logged): %s",
                     self.run_id, exc)

    def _write(self, event_type, fields):
        """Write one event line and flush it. The caller holds self._lock."""
        event = {
            "v": FORMAT_VERSION,
            "type": event_type,
            "t": time.time(),
            # Allocated before the write, so a lost line leaves a gap in seq.
            "seq": self._seq,
            "run_id": self.run_id,
        }
        self._seq += 1
        event.update(fields)
        self._handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._handle.flush()

    def _emit(self, event_type, fields):
        """Write one event unless the run has ended. Returns True if it was written."""
        with self._lock:
            if self._closed:
                return False
            self._write(event_type, fields)
            return True

    def _close_handle(self):
        self._closed = True
        try:
            self._handle.close()
        except Exception as exc:
            self._warn(exc)

    @_guarded
    def phase(self, name):
        self._emit("phase", {"phase": _text(name)})

    @_guarded
    def progress(self, phase, pct, detail=None):
        phase = _text(phase)
        detail = _text(detail)
        value = _num(pct)
        if value is None:
            return
        value = round(min(100.0, max(0.0, value)), 1)
        key = (phase, detail, int(value))
        if key == self._last_progress:
            return
        if self._emit("progress", {"phase": phase, "pct": value, "detail": detail}):
            self._last_progress = key

    @_guarded
    def audio(self, duration, start_offset):
        self._emit("audio", {"duration": _num(duration), "start_offset": _num(start_offset)})

    @_guarded
    def diarization(self, segments):
        segments = list(segments or [])
        speakers = sorted({f"S{str(seg['label'])[8:]}" for seg in segments})
        self._emit("diarization", {"speakers": speakers, "turns": len(segments)})

    @_guarded
    def model_ready(self, device, device_name, compute_type, load_seconds):
        self._emit("model_ready", {
            "component": "whisper",
            "device": _text(device),
            "device_name": _text(device_name),
            "compute_type": _text(compute_type),
            "load_seconds": _num(load_seconds, 2),
        })

    @_guarded
    def language(self, code, probability):
        self._emit("language", {"language": _text(code), "probability": _num(probability)})

    @_guarded
    def segment(self, index, start, end, speaker, text):
        self._emit("segment", {
            "index": int(index),
            "start": _num(start),
            "end": _num(end),
            "speaker": "" if speaker is None else str(speaker),
            "text": "" if text is None else str(text),
        })

    def end(self, status, error=None, output_file=None):
        """Write run_end and close the file. Only the first call has any effect."""
        with self._lock:
            if self._closed:
                return
            try:
                self._write("run_end", {
                    "status": _text(status),
                    "error": _text(error),
                    "output_file": _text(output_file),
                    "elapsed": _num(time.monotonic() - self._started, 2),
                })
            except Exception as exc:
                self._warn(exc)
            finally:
                self._close_handle()


def _run_start_fields(job, model_name, noscribe_version):
    return {
        "audio_file": _abspath(getattr(job, "audio_file", None)),
        "output_file": _abspath(getattr(job, "transcript_file", None)),
        "model": _text(model_name),
        "language": _text(getattr(job, "language_name", None)),
        "speaker_detection": str(getattr(job, "speaker_detection", None)),
        "options": {
            "overlapping": bool(getattr(job, "overlapping", False)),
            "timestamps": bool(getattr(job, "timestamps", False)),
            "disfluencies": bool(getattr(job, "disfluencies", False)),
            "pause": _plain(getattr(job, "pause", None)),
        },
        "pid": os.getpid(),
        "noscribe_version": _text(noscribe_version),
    }


def _open_feed(target, job, model_name, noscribe_version):
    base = _run_id_base(getattr(job, "audio_file", None))
    if _is_directory_target(target):
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        run_id, handle = _create_in_directory(directory, base)
    else:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        run_id = _reserve_run_id(base)
        handle = open(path, "a", encoding="utf-8", newline="\n", buffering=1)
    feed = JobFeed(run_id, handle)
    try:
        feed._emit("run_start", _run_start_fields(job, model_name, noscribe_version))
    except BaseException:
        feed._close_handle()
        raise
    return feed


def open_job(job, model_name, noscribe_version=None):
    """Start the feed for one job and write its run_start event.

    Returns a JobFeed. If no target is configured, or the feed cannot be opened,
    the returned feed is a silent no-op and the transcription goes on unchanged.
    """
    target = _resolve_target()
    if target is None:
        return JobFeed.disabled()
    try:
        return _open_feed(target, job, model_name, noscribe_version)
    except Exception as exc:
        _log.warning("live feed could not be opened for this job: %s", exc)
        return JobFeed.disabled()
