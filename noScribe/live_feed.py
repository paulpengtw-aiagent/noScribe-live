"""Opt-in live feed of a transcription, written as NDJSON (one JSON object per line).

Enabled with ``--live-feed PATH`` or the ``NOSCRIBE_LIVE_FEED`` environment
variable; the flag wins. Without a target every call here does nothing: no file
is created and nothing is printed.

The event format is documented in ``live/FEED.md``. This module is stdlib only,
and every ``JobFeed`` method swallows its own exceptions (the first one is logged
as a warning), so a feed problem can never change or stop a transcription.

While a job's feed is open, the CLI's own log records and stdout/stderr text are
also forwarded as ``log`` events (see the section above ``_run_start_fields``).
The terminal output does not change: every write reaches the original stream first.
"""

import contextlib
import functools
import json
import logging
import math
import os
import re
import sys
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
        # Log forwarding, installed by _start_capture() and removed by _stop_capture().
        self._forwarder = None
        self._log_handler = None
        self._tee_out = self._orig_out = None
        self._tee_err = self._orig_err = None

    @classmethod
    def disabled(cls):
        """A feed that ignores every call and touches nothing."""
        return cls()

    def _warn(self, exc):
        if self._warned:
            return
        self._warned = True
        with _feed_code():   # the feed's own warning is not forwarded back into the feed
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
        self._stop_capture()   # first, so the held-back log lines go out before run_end
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

    def _start_capture(self):
        """Forward the CLI's log records and stdout/stderr text to this feed until end()."""
        if self._closed or self._forwarder is not None:
            return
        try:
            self._forwarder = _LogForwarder(self)
            self._log_handler = _FeedLogHandler(self._forwarder)
            logging.getLogger().addHandler(self._log_handler)
            if sys.stdout is not None:
                self._orig_out = sys.stdout
                self._tee_out = _TeeStream(sys.stdout, "stdout", self._forwarder)
                sys.stdout = self._tee_out
            if sys.stderr is not None:
                self._orig_err = sys.stderr
                self._tee_err = _TeeStream(sys.stderr, "stderr", self._forwarder)
                sys.stderr = self._tee_err
            _live_captures.append(self)
        except Exception as exc:
            self._stop_capture()
            self._warn(exc)

    def _stop_capture(self):
        """Put back the streams and the logging handler. Safe to call more than once."""
        forwarder, self._forwarder = self._forwarder, None
        if forwarder is None:
            return
        try:
            if self in _live_captures:
                _live_captures.remove(self)
            for name, tee, original in (("stdout", self._tee_out, self._orig_out),
                                        ("stderr", self._tee_err, self._orig_err)):
                if tee is None:
                    continue
                tee._done = True
                if getattr(sys, name) is tee:
                    setattr(sys, name, _unwound(original))
            handler, self._log_handler = self._log_handler, None
            if handler is not None:
                logging.getLogger().removeHandler(handler)
        except Exception as exc:
            self._warn(exc)
        finally:
            forwarder.close()


# ---------------------------------------------------------------------------
# Log forwarding. While a job's feed is open, the CLI's log records and its
# stdout/stderr text are written as "log" events too. Only JobFeed._start_capture
# installs any of this, and only when the feed is on.
# ---------------------------------------------------------------------------

LOG_RATE_PER_S = 20        # at most this many log events per second (a token bucket of the same size)
LOG_MAX_CHARS = 300        # longer messages are cut and end with "..."
PROGRESS_MIN_INTERVAL_S = 0.2   # progress updates on one unfinished line are sent at most this often (100% always is)
_PENDING_LIMIT = 4096      # text this long without a line break is sent in pieces
_KNOWN_SOURCES = ("faster_whisper", "pyannote", "ctranslate2", "speechbrain", "torch")

_BREAK_RE = re.compile(r"(\r\n|\r|\n)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_RE = re.compile(r"(?i)token\s*=|authorization|bearer\s|api[_-]?key|secret|passw"
                        r"|\bhf_\w{8,}|\bsk-[\w-]{8,}")
# A /path/to/name or C:\path\to\name, trimmed to its last component.
_PATH_RE = re.compile(r"(?<![\w.:/\\])(?:[A-Za-z]:)?[\\/](?=[^\\/\s])(?:[^\\/\r\n]+[\\/])*([^\\/\r\n]+)")
_ERROR_START_RE = re.compile(r"\s*(error|fatal|critical)\b", re.IGNORECASE)
# A progress update such as "segmentation: 16%". Several can run together on one line that has no break yet.
_PROGRESS_RE = re.compile(r"([A-Za-z][\w .-]{0,40}):\s*(\d{1,3})%")

_monotonic = time.monotonic    # tests replace this to make the rate limit deterministic
_feed_local = threading.local()
_live_captures = []            # JobFeeds that are forwarding right now


@contextlib.contextmanager
def _feed_code():
    """Code that acts for the feed. Log records and writes made inside it are not forwarded."""
    previous = getattr(_feed_local, "active", False)
    _feed_local.active = True
    try:
        yield
    finally:
        _feed_local.active = previous


def _in_feed_code():
    return getattr(_feed_local, "active", False)


def _clean(text):
    """The text to send for one line, or None when there is nothing to send."""
    text = _ANSI_RE.sub("", text).strip()
    if not text:
        return None
    if _SECRET_RE.search(text):
        return "[redacted]"
    text = _PATH_RE.sub(lambda m: m.group(1), text)
    if len(text) > LOG_MAX_CHARS:
        text = text[:LOG_MAX_CHARS - 3] + "..."
    return text


def _source_for(name):
    top = str(name or "").split(".", 1)[0]
    if top in _KNOWN_SOURCES:
        return top
    if top in ("", "root", "__main__", "noScribe"):
        return "noScribe"
    return re.sub(r"[^\w-]", "_", top)[:40] or "other"


def _level_for(levelno):
    if levelno >= logging.ERROR:
        return "error"
    if levelno >= logging.WARNING:
        return "warning"
    if levelno >= logging.INFO:
        return "info"
    return "debug"


def _unwound(stream):
    """The stream to put back. Tees that were stopped already (out of order) are skipped."""
    while isinstance(stream, _TeeStream) and stream._done:
        stream = stream._original
    return stream


class _LogForwarder:
    """Turns stdout/stderr text and log records into "log" events of one JobFeed.

    Safe to call from any thread. A failure disables forwarding for the run (the
    feed logs the first one) and never reaches the code that wrote the text.
    """

    def __init__(self, feed):
        self._feed = feed
        self._pid = os.getpid()    # a forked child inherits this object; only the owner process forwards
        self._mutex = threading.Lock()
        self._tokens = float(LOG_RATE_PER_S)
        self._stamp = _monotonic()
        self._skipped = 0          # lines held back by the rate limit since the last note
        self._last_key = None      # (source, level, msg, replace) of the newest event sent
        self._pending = None       # the newest progress line the rate limit held back
        self._partial = {"stdout": "", "stderr": ""}          # text after the last line break
        self._progress = {"stdout": False, "stderr": False}   # the last break was a \r update
        self._last_progress = {"stdout": None, "stderr": None}   # (text, percent) of the newest progress update on the line
        self._progress_sent_at = {"stdout": float("-inf"), "stderr": float("-inf")}
        self.disabled = False
        self._closed = False

    def feed_text(self, stream, text):
        if self.disabled or self._closed or _in_feed_code() or os.getpid() != self._pid:
            return
        try:
            with self._mutex:
                if not self._closed:
                    self._split(stream, text)
        except Exception as exc:
            self.disable(exc)

    def log_record(self, record):
        if self.disabled or self._closed or os.getpid() != self._pid:
            return
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        text = " | ".join(part for part in message.splitlines() if part.strip())
        with self._mutex:
            if not self._closed:
                self._offer(_source_for(record.name), _level_for(record.levelno), text, False)

    def disable(self, exc):
        """Stop forwarding for this run. The feed logs the first error once."""
        if not self.disabled:
            self.disabled = True
            self._feed._warn(exc)

    def close(self):
        """Send what the rate limit held back: a partial line, the skipped count, the last progress."""
        try:
            with self._mutex:
                if self._closed:
                    return
                for stream in ("stdout", "stderr"):
                    rest, self._partial[stream] = self._partial[stream], ""
                    if rest or self._last_progress[stream] is not None:
                        self._line(stream, rest, "")
                pending, self._pending = self._pending, None
                resend = pending is not None and pending != self._last_key
                if self._skipped:
                    self._note()
                if resend:
                    self._send(pending)
        except Exception as exc:
            self.disable(exc)
        finally:
            self._closed = True

    def _split(self, stream, text):
        buf = self._partial[stream] + text
        hold = ""
        if buf.endswith("\r"):     # a \r may be the first half of \r\n: wait for the next write
            buf, hold = buf[:-1], "\r"
        pieces = _BREAK_RE.split(buf)      # text, break, text, break, ..., text
        for i in range(0, len(pieces) - 1, 2):
            self._line(stream, self._take_progress(stream, pieces[i]), pieces[i + 1])
        rest = self._take_progress(stream, pieces[-1]) + hold
        if len(rest) > _PENDING_LIMIT:
            self._line(stream, rest, "\n")
            rest = ""
        self._partial[stream] = rest

    def _line(self, stream, text, brk):
        if brk == "\r":            # a progress update: the viewer replaces its line in place
            self._progress[stream] = True
            replace = True
        else:                      # a finished line replaces the progress line before it, if any
            replace = self._progress[stream]
            self._progress[stream] = False
            last, self._last_progress[stream] = self._last_progress[stream], None
            if last is not None and last[1] < 100:   # the newest progress update, if it was held back (100% was sent)
                self._emit_text(stream, last[0], True)
        self._emit_text(stream, text, replace)

    def _emit_text(self, stream, text, replace):
        if _ERROR_START_RE.match(text):
            level = "error"
        elif stream == "stderr" and not replace:
            level = "warning"
        else:
            level = "info"
        self._offer(stream, level, text, replace)

    def _take_progress(self, stream, text):
        """Forward the progress updates in text (which has no line break) and return the rest of the text."""
        rest, pos = [], 0
        for m in _PROGRESS_RE.finditer(text):
            rest.append(text[pos:m.start()])
            pos = m.end()
            self._progress_update(stream, m.group(0), int(m.group(2)))
        rest.append(text[pos:])
        return "".join(rest)

    def _progress_update(self, stream, text, pct):
        """A progress update that has no line break after it, so the CLI's line is still open.

        Each update replaces the line's progress in the feed. Updates closer together than
        PROGRESS_MIN_INTERVAL_S are held back; the newest one is sent when the line ends (see
        _line). 100% is always sent at once. The terminal already has every write.
        """
        self._last_progress[stream] = (text, pct)
        self._progress[stream] = True
        now = _monotonic()
        if pct >= 100 or now - self._progress_sent_at[stream] >= PROGRESS_MIN_INTERVAL_S:
            self._progress_sent_at[stream] = now
            self._emit_text(stream, text, True)

    def _offer(self, source, level, text, replace):
        msg = _clean(text[:_PENDING_LIMIT])
        if msg is None:
            return
        key = (source, level, msg, replace)
        if key == self._last_key:  # the same line as the one just sent: coalesced
            return
        if self._take_token():
            if self._skipped:
                self._note()
            self._pending = None
            self._send(key)
        else:
            self._skipped += 1
            if replace:
                self._pending = key    # only the newest progress state is worth keeping

    def _take_token(self):
        now = _monotonic()
        self._tokens = min(float(LOG_RATE_PER_S), self._tokens + (now - self._stamp) * LOG_RATE_PER_S)
        self._stamp = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _note(self):
        count, self._skipped = self._skipped, 0
        self._send(("live_feed", "info", f"({count} lines skipped)", False))

    def _send(self, key):
        source, level, msg, replace = key
        self._last_key = key
        fields = {"level": level, "source": source, "msg": msg}
        if replace:
            fields["replace"] = True
        self._feed._emit("log", fields)


class _FeedLogHandler(logging.Handler):
    """Root-logger handler for the feed. It only filters: no existing handler or level changes."""

    def __init__(self, forwarder):
        super().__init__(level=logging.INFO)
        self._forwarder = forwarder

    def emit(self, record):
        if _in_feed_code():
            return
        try:
            self._forwarder.log_record(record)
        except Exception as exc:
            self._forwarder.disable(exc)


class _TeeStream:
    """Stands in for sys.stdout or sys.stderr. Each write goes to the original stream unchanged, then to the feed."""

    def __init__(self, original, name, forwarder):
        self._original = original
        self._name = name
        self._forwarder = forwarder
        self._done = False

    def write(self, text):
        result = self._original.write(text)
        if not self._done:
            self._forwarder.feed_text(self._name, text)
        return result

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        # flush, isatty, encoding, fileno, buffer and the rest belong to the original stream
        original = self.__dict__.get("_original")
        if original is None:
            raise AttributeError(name)
        return getattr(original, name)


def _stop_all_captures():
    """Stop every forwarding that is still installed. For tests and cleanup."""
    for feed in list(_live_captures):
        feed._stop_capture()


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
    feed._start_capture()
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
