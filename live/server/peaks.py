"""Waveform peaks for the viewer's audio timeline.

``compute_peaks`` decodes the file with ffmpeg as a stream of 8 kHz mono signed
16-bit samples, read in small chunks, so the audio is never held in memory whole.
Samples are assigned to ``n`` equal-time buckets and each bucket gets its RMS level.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_RATE = 8000          # decode rate; plenty for an envelope
READ_BYTES = 64 * 1024      # about 4 s of audio per read
PERCENTILE = 98             # this percentile of the bucket RMS values maps to 1.0


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise RuntimeError(f"{tool} is not installed or not on PATH")


class AudioDecodeError(RuntimeError):
    """ffprobe or ffmpeg cannot read audio from an existing file (empty, corrupt, not audio).
    The message is short and has no paths, so the viewer may show it."""


def _reason(stderr: str, source: str) -> str:
    """The last non-empty stderr line, with the input's absolute path replaced by its file name."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    text = lines[-1].replace(source, Path(source).name) if lines else ""
    return text[:200] or "no details from the decoder"


def probe_duration(path: str | Path) -> float:
    """Duration of the file in seconds, as reported by ffprobe. Raises AudioDecodeError if ffprobe cannot read it."""
    _require("ffprobe")
    source = str(Path(path).resolve())
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", source],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        raise AudioDecodeError(_reason(proc.stderr, source))
    try:
        return float(proc.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        raise AudioDecodeError("no duration reported") from None


def compute_peaks(path: str | Path, n: int) -> tuple[float, list[float]]:
    """Return ``(duration_seconds, peaks)`` with ``n`` values in 0..1 for the audio file at ``path``."""
    if n < 1:
        raise ValueError("n must be at least 1")
    _require("ffmpeg")
    source = str(Path(path).resolve())
    duration = probe_duration(source)
    # Estimated total sample count. Bucket index = sample index * n // total, so the buckets
    # span the whole file; any overshoot (encoder padding) lands in the last bucket.
    total = max(1, round(duration * SAMPLE_RATE))

    sums = np.zeros(n)
    counts = np.zeros(n)
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", source,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    # stderr goes to a temporary file so ffmpeg can never block on a full stderr pipe.
    with tempfile.TemporaryFile() as errlog:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errlog)
        try:
            index = 0      # samples consumed so far
            carry = b""    # odd byte left over when a read splits a 16-bit sample
            while True:
                chunk = proc.stdout.read(READ_BYTES)
                if not chunk:
                    break
                data = carry + chunk
                usable = len(data) - len(data) % 2
                carry = data[usable:]
                samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float64) / 32768.0
                if samples.size == 0:
                    continue
                idx = np.arange(index, index + samples.size, dtype=np.int64)
                buckets = np.minimum(idx * n // total, n - 1)
                sums += np.bincount(buckets, weights=samples * samples, minlength=n)
                counts += np.bincount(buckets, minlength=n)
                index += samples.size
        finally:
            proc.stdout.close()
            returncode = proc.wait()
        if returncode != 0:
            errlog.seek(0)
            message = errlog.read().decode("utf-8", errors="replace")
            raise AudioDecodeError(_reason(message, source))
        if index == 0:
            raise AudioDecodeError("no audio samples could be decoded")

    rms = np.sqrt(np.divide(sums, counts, out=np.zeros(n), where=counts > 0))
    reference = float(np.percentile(rms, PERCENTILE))
    if reference > 0:
        peaks = np.clip(rms / reference, 0.0, 1.0)
    else:  # silence
        peaks = np.zeros(n)
    return duration, [round(float(value), 3) for value in peaks]
