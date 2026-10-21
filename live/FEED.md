# noScribe Live feed format

While a job runs, the CLI can write one JSON object per line (NDJSON) to a feed. The viewer in `live/` tails these files. The writer is [`noScribe/live_feed.py`](../noScribe/live_feed.py), and the `--live-feed` flag is defined in `noScribe/main.py`. Every line has `"v": 1`, the format version.

## Enabling

- `--live-feed PATH`, or the environment variable `NOSCRIBE_LIVE_FEED`. The flag wins. `--live-feed ""` turns the feed off even when the variable is set.
- With neither, nothing is created or printed, and the transcription is unchanged.
- Directory mode: `PATH` ends with `/` or is an existing directory. Each job writes `PATH/<run_id>.ndjson`, created exclusively (a clash gets `-2`, `-3`, ...).
- File mode: any other `PATH`. Every run is appended to that one file. Run ids are unique within one process.
- `run_id` is `YYYYMMDD-HHMMSS-<audio file stem>`. Characters other than letters, digits, `_`, `.` and `-` become `_`, and the stem is cut to 60 characters. Example: `20261020-051028-demo-en-zh`.
- Each line is flushed when it is written. A feed error is logged once and never stops the transcription.

## Common keys

| key | meaning |
|---|---|
| `v` | format version (1) |
| `type` | event type, see the table below |
| `t` | epoch seconds (float), CLI clock |
| `seq` | 0-based counter per run; a gap means a line was lost |
| `run_id` | the run the line belongs to |

## Events

| type | written when | event keys (besides the common keys) |
|---|---|---|
| `run_start` | the job starts | `audio_file`, `output_file` (absolute paths), `model`, `language`, `speaker_detection`, `options` (`overlapping`, `timestamps`, `disfluencies`, `pause`), `pid` (the CLI process; the viewer uses it to spot a killed run), `noscribe_version` |
| `phase` | a stage starts: `converting`, `diarizing`, `transcribing` | `phase` |
| `progress` | percent within a phase; a repeat of the same phase, detail and whole percent is skipped | `phase`, `pct` (0-100), `detail` (`segmentation` or `embeddings` while diarizing, otherwise null) |
| `audio` | the audio duration is known | `duration` (s), `start_offset` (s) |
| `diarization` | speaker turns are known | `speakers` (such as `S00`, from `SPEAKER_00`), `turns` (count) |
| `model_ready` | the Whisper model is loaded | `component` (`whisper`), `device`, `device_name`, `compute_type`, `load_seconds` |
| `language` | the language is detected or set | `language`, `probability` (may be null) |
| `segment` | a segment is finished | `index` (0-based, restarts per attempt), `start`, `end` (s, original audio timeline), `speaker`, `text` |
| `run_end` | the job ends; written once, then the file closes | `status` (`finished`, `canceled` or `error`), `error`, `output_file`, `elapsed` (s) |
| `log` | while the feed is open: a logging record (INFO and up, see below) or a line the CLI prints to stdout or stderr | `level` (`debug`, `info`, `warning`, `error`), `source`, `msg`, `replace` (present only when true) |

### `log` events

- Only while the feed is on. With the feed off, no logging handler is attached and the streams are not touched.
- **What is forwarded.** A handler on the root logger passes records at INFO and up. It does not change any logger level or existing handler, so a record appears only when its logger already emits it. In `main.py`, `faster_whisper` is at DEBUG, so its INFO records show; most other libraries show WARNING and up. Text written to `sys.stdout` and `sys.stderr` is forwarded too. The terminal output is unchanged: each write reaches the original stream first, unchanged.
- **`source`.** For log records: `faster_whisper`, `pyannote`, `ctranslate2`, `speechbrain` or `torch` (by logger name), `noScribe` for `noScribe.*` and the root logger, and otherwise the top-level package name. For text: `stdout` or `stderr`. The feed's own note (see the rate limit) has source `live_feed`.
- **`level`.** Records map from their logging level. Stdout lines are `info`. Stderr lines are `warning`, unless they start with `ERROR`, `FATAL` or `CRITICAL`, which makes them `error`. Progress updates are `info`.
- **`replace`.** A carriage-return update (for example a progress bar) is sent with `"replace": true`. So is the line that finishes it, the one that ends with a newline. The viewer replaces its last progress line in place. Lines without the flag are appended.
- **Rate limit.** At most 20 log events per second, as a token bucket. Lines over the limit are dropped and counted. The next event sent is preceded by `(n lines skipped)` (source `live_feed`, level `info`). At the end of the run, the last progress state and the final count are sent before `run_end`. An identical line directly after the same line is sent once.
- **Hygiene.** ANSI colour codes are removed. Messages are cut to 300 characters and end with `...`. A path such as `/a/b/name.mp3` or `C:\a\b\name.mp3` becomes `name.mp3`. URLs are not trimmed.
- **Privacy.** A line that contains `token=`, `Authorization`, `Bearer`, `api_key`, `secret`, `password`, a Hugging Face token (`hf_...`) or an `sk-...` key is replaced by `[redacted]`. This is pattern matching only. Other text the CLI prints can still reach the feed, and the file may contain transcript text from log lines, so treat it as sensitive.
- **Failure.** If forwarding raises, forwarding stops for the run, the feed logs one warning, and the transcription and the terminal output go on unchanged.

Examples, verbatim from `live/` code run on a sample (the `run_start`, `phase` and `segment` lines are omitted):

```json
{"v": 1, "type": "log", "t": 1792600161.6185153, "seq": 1, "run_id": "20261022-002921-demo-en-zh", "level": "info", "source": "stdout", "msg": "Output saved to: demo-en-zh.html"}
{"v": 1, "type": "log", "t": 1792600161.6185684, "seq": 2, "run_id": "20261022-002921-demo-en-zh", "level": "info", "source": "stderr", "msg": "transcribing 40%|####      |", "replace": true}
{"v": 1, "type": "log", "t": 1792600161.618664, "seq": 4, "run_id": "20261022-002921-demo-en-zh", "level": "warning", "source": "pyannote", "msg": "std warning from seg.bin"}
```

Examples are verbatim lines from one real run of `live/samples/demo-en-zh.mp3`. `seq` shows each line's place in that run.

```json
{"v": 1, "type": "run_start", "t": 1792444228.5503454, "seq": 0, "run_id": "20261020-051028-demo-en-zh", "audio_file": "/workspace/noScribe-live/live/samples/demo-en-zh.mp3", "output_file": "/tmp/nslive-e2e/demo-en-zh.html", "model": "breeze-asr-25", "language": "Auto", "speaker_detection": "auto", "options": {"overlapping": true, "timestamps": true, "disfluencies": true, "pause": 1}, "pid": 3456054, "noscribe_version": "0.8"}
{"v": 1, "type": "phase", "t": 1792444228.5507102, "seq": 1, "run_id": "20261020-051028-demo-en-zh", "phase": "converting"}
{"v": 1, "type": "progress", "t": 1792444234.6703916, "seq": 3, "run_id": "20261020-051028-demo-en-zh", "phase": "diarizing", "pct": 0.0, "detail": "segmentation"}
{"v": 1, "type": "audio", "t": 1792444243.8361804, "seq": 33, "run_id": "20261020-051028-demo-en-zh", "duration": 202.4, "start_offset": 0.0}
{"v": 1, "type": "diarization", "t": 1792444243.744259, "seq": 31, "run_id": "20261020-051028-demo-en-zh", "speakers": ["S00", "S01"], "turns": 69}
{"v": 1, "type": "model_ready", "t": 1792444264.4610252, "seq": 34, "run_id": "20261020-051028-demo-en-zh", "component": "whisper", "device": "cuda", "device_name": "NVIDIA GeForce RTX 5060 Ti", "compute_type": "default", "load_seconds": 20.2}
{"v": 1, "type": "language", "t": 1792444265.8101544, "seq": 35, "run_id": "20261020-051028-demo-en-zh", "language": "zh", "probability": 0.97412109375}
{"v": 1, "type": "segment", "t": 1792444268.0938783, "seq": 36, "run_id": "20261020-051028-demo-en-zh", "index": 0, "start": 2.25, "end": 6.848, "speaker": "S00", "text": "This is a LibriVox recording. All LibriVox recordings are in the public domain."}
{"v": 1, "type": "run_end", "t": 1792444278.8053226, "seq": 132, "run_id": "20261020-051028-demo-en-zh", "status": "finished", "error": null, "output_file": "/tmp/nslive-e2e/demo-en-zh.html", "elapsed": 50.25}
```
