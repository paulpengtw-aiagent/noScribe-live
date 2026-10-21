#!/usr/bin/env bash
# One guarded real noScribe run with the noScribe Live recorder attached.
#
# Usage: live/stress/run_real.sh AUDIO OUTDIR [extra noScribe args...]
#   Extra args go before AUDIO (e.g. --stop 00:01:00 --language en).
#
# Environment:
#   NOSCRIBE_PY   Python with noScribe (default /home/cheng/noScribe/venv/bin/python)
#   MODEL         Whisper model (default breeze-asr-25)
#   LIVE_FEED     feed directory for --live-feed (default live/feeds/); "off" runs without the feed and recorder
#   RECORDER_ARGS extra args for live/stress/recorder.py, e.g. "--widths 1440" or "--join-after 20"
#   VIEW_URL      viewer URL (default http://127.0.0.1:8765/)
#
# Writes OUTDIR/{cli.log,rss.tsv,recorder/,recorder.log,recorder.summary.json,result.json} and appends one
# line to live/stress/results/results.tsv. Exit 3 means the resource guard gave up after 20 min.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: live/stress/run_real.sh AUDIO OUTDIR [extra noScribe args...]" >&2
  exit 2
fi
AUDIO_IN="$1"
OUTDIR_IN="$2"
shift 2
EXTRA_ARGS=("$@")

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
NOSCRIBE_PY="${NOSCRIBE_PY:-/home/cheng/noScribe/venv/bin/python}"
MODEL="${MODEL:-breeze-asr-25}"
LIVE_FEED="${LIVE_FEED:-live/feeds/}"
RECORDER_ARGS="${RECORDER_ARGS:-}"
VIEW_URL="${VIEW_URL:-http://127.0.0.1:8765/}"
RECORDER_PY="/usr/bin/python3"
RESULTS_DIR="$HERE/results"
RESULTS_TSV="$RESULTS_DIR/results.tsv"

[[ -f "$AUDIO_IN" ]] || { echo "run_real: audio not found: $AUDIO_IN" >&2; exit 2; }
mkdir -p "$OUTDIR_IN"
OUTDIR="$(cd "$OUTDIR_IN" && pwd)"
AUDIO="$(cd "$(dirname "$AUDIO_IN")" && pwd)/$(basename "$AUDIO_IN")"
STEM="$(basename "$AUDIO" | sed 's/\.[^.]*$//')"
cd "$REPO_ROOT"

# ---- 1. resource guard: >= 4 GiB free in the cgroup and no other GPU compute process ----------------
MIN_FREE=$((4 * 1024 * 1024 * 1024))
GUARD_DEADLINE=$(( $(date +%s) + 1200 ))
while true; do
  reasons=""
  mem_max="$(cat /sys/fs/cgroup/memory.max)"
  if [[ "$mem_max" == "max" ]]; then
    mem_max="$(awk '/^MemTotal:/{print $2*1024}' /proc/meminfo)"
  fi
  mem_cur="$(cat /sys/fs/cgroup/memory.current)"
  inactive="$(awk '$1=="inactive_file"{print $2}' /sys/fs/cgroup/memory.stat)"
  free=$(( mem_max - mem_cur + inactive ))
  if (( free < MIN_FREE )); then
    reasons+="free memory $(( free / 1024 / 1024 )) MiB < 4096 MiB; "
  fi
  gpu_pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null || echo "nvidia-smi failed")"
  if [[ -n "$gpu_pids" ]]; then
    reasons+="GPU compute processes present: $(echo "$gpu_pids" | tr '\n' ' '); "
  fi
  if [[ -z "$reasons" ]]; then
    echo "guard: free $(( free / 1024 / 1024 )) MiB, GPU idle, go" >&2
    break
  fi
  if (( $(date +%s) >= GUARD_DEADLINE )); then
    echo "guard: gave up after 20 min, still waiting for: $reasons" >&2
    exit 3
  fi
  echo "guard: waiting for: $reasons" >&2
  sleep 15
done

# ---- 2. recorder in the background (not with LIVE_FEED=off) --------------------------------------
RECORDER_PID=""
FEED_ARGS=()
if [[ "$LIVE_FEED" != "off" ]]; then
  FEED_ARGS=(--live-feed "$LIVE_FEED")
  read -r -a REC_EXTRA <<< "$RECORDER_ARGS"
  "$RECORDER_PY" -I "$HERE/recorder.py" --url "$VIEW_URL" --out "$OUTDIR/recorder" --until-run-end \
    ${REC_EXTRA[@]+"${REC_EXTRA[@]}"} > "$OUTDIR/recorder.summary.json" 2> "$OUTDIR/recorder.log" &
  RECORDER_PID=$!
  echo "recorder: pid $RECORDER_PID, viewer $VIEW_URL" >&2
fi

# ---- 3. the CLI, with RSS sampling of its process tree --------------------------------------------
CLI_LOG="$OUTDIR/cli.log"
CLI_OUT="$OUTDIR/$STEM.html"
PYTHONDONTWRITEBYTECODE=1 "$NOSCRIBE_PY" -m noScribe --no-gui --model "$MODEL" --speaker-detection auto \
  --timestamps ${FEED_ARGS[@]+"${FEED_ARGS[@]}"} "${EXTRA_ARGS[@]}" "$AUDIO" "$CLI_OUT" > "$CLI_LOG" 2>&1 &
CLI_PID=$!
echo "cli: pid $CLI_PID, model $MODEL, feed $LIVE_FEED" >&2

"$RECORDER_PY" -I - "$CLI_PID" "$OUTDIR/rss.tsv" <<'PY' &
import os, sys, time
root, out = int(sys.argv[1]), sys.argv[2]


def children_map():
    kids = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as fh:
                data = fh.read()
            ppid = int(data[data.rfind(")") + 2:].split()[1])
            kids.setdefault(ppid, []).append(int(name))
        except (OSError, ValueError, IndexError):
            pass
    return kids


def rss_kb(pid):
    try:
        with open(f"/proc/{pid}/statm") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") // 1024
    except (OSError, ValueError, IndexError):
        return 0


with open(out, "w", encoding="utf-8") as fh:
    fh.write("t\tprocs\trss_kb\n")
    while os.path.exists(f"/proc/{root}"):
        kids = children_map()
        pids, stack = [], [root]
        while stack:
            pid = stack.pop()
            pids.append(pid)
            stack.extend(kids.get(pid, []))
        total = sum(rss_kb(p) for p in pids)
        fh.write(f"{time.time():.2f}\t{len(pids)}\t{total}\n")
        fh.flush()
        time.sleep(2)
PY
SAMPLER_PID=$!

T0="$(date +%s.%N)"
set +e
wait "$CLI_PID"
CLI_RC=$?
set -e
T1="$(date +%s.%N)"
wait "$SAMPLER_PID" 2>/dev/null || true
WALL_S="$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.3f", b-a}')"
echo "cli: exit $CLI_RC after ${WALL_S}s" >&2

# ---- 4. wait for the recorder (at most 60 s after the CLI exits) ---------------------------------
REC_RC=""
if [[ -n "$RECORDER_PID" ]]; then
  waited=0
  while kill -0 "$RECORDER_PID" 2>/dev/null && (( waited < 60 )); do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$RECORDER_PID" 2>/dev/null; then
    echo "recorder: still running 60 s after the CLI exited, sending SIGTERM" >&2
    kill -TERM "$RECORDER_PID" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$RECORDER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "$RECORDER_PID" 2>/dev/null || true
  fi
  set +e
  wait "$RECORDER_PID"
  REC_RC=$?
  set -e
  echo "recorder: exit ${REC_RC}" >&2
fi

# ---- 5. result.json and results.tsv ---------------------------------------------------------------
# ffprobe fails on undecodable input (and some builds print N/A): keep only a plain number, else the
# duration is unknown and audio_s and rtf stay null. This step must never abort the script.
AUDIO_S="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO" 2>/dev/null | head -n 1 || true)"
if [[ ! "$AUDIO_S" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
  echo "run_real: ffprobe gave no usable duration for $AUDIO; audio_s and rtf are null" >&2
  AUDIO_S=""
fi
EXTRA_JSON="$(printf '%s\n' ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} | /usr/bin/python3 -I -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().split("\n") if l]))')"
mkdir -p "$RESULTS_DIR"
if ! /usr/bin/python3 -I - "$OUTDIR" "$AUDIO" "$MODEL" "$EXTRA_JSON" "$CLI_RC" "$WALL_S" "${AUDIO_S:-}" \
  "$REPO_ROOT" "$LIVE_FEED" "${REC_RC:-}" "$RESULTS_TSV" "$RECORDER_ARGS" <<'PY'
import glob, json, math, os, sys, time

(outdir, audio, model, extra_json, cli_rc, wall_s, audio_s, repo_root, live_feed,
 rec_rc, results_tsv, recorder_args) = sys.argv[1:13]


def number(text):
    """A finite positive float, or None for empty, N/A or otherwise unusable text."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


extra = json.loads(extra_json)
wall = number(wall_s) or 0.0
audio_len = number(audio_s)

# Newest feed file whose run_start names this audio file.
feed_file, run_id, status, segments = None, None, None, None
audio_real = os.path.realpath(audio)
best = None
for path in glob.glob(os.path.join(repo_root, "live", "feeds", "*.ndjson")):
    try:
        with open(path, encoding="utf-8") as fh:
            first = json.loads(fh.readline() or "{}")
    except (OSError, ValueError):
        continue
    if not isinstance(first, dict) or first.get("type") != "run_start" or not isinstance(first.get("audio_file"), str):
        continue
    if os.path.realpath(first["audio_file"]) != audio_real:
        continue
    mtime = os.path.getmtime(path)
    if best is None or mtime > best[0]:
        best = (mtime, path, first.get("run_id"))
if best is not None:
    _, feed_file, run_id = best
    segments = 0
    with open(feed_file, encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "segment":
                segments += 1
            elif ev.get("type") == "run_end":
                status = ev.get("status")

peak_kb = 0
rss_path = os.path.join(outdir, "rss.tsv")
if os.path.exists(rss_path):
    with open(rss_path, encoding="utf-8") as fh:
        for row in list(fh)[1:]:
            parts = row.split("\t")
            if len(parts) == 3 and parts[2].strip().isdigit():
                peak_kb = max(peak_kb, int(parts[2]))

recorder = None
summary_path = os.path.join(outdir, "recorder.summary.json")
if os.path.exists(summary_path):
    try:
        with open(summary_path, encoding="utf-8") as fh:
            recorder = json.loads(fh.read().strip().splitlines()[-1])
    except (OSError, ValueError, IndexError):
        recorder = None

result = {
    "audio": audio,
    "model": model,
    "extra_args": extra,
    "live_feed": live_feed,
    "exit_code": int(cli_rc),
    "wall_s": round(wall, 3),
    "audio_s": audio_len,
    "rtf": round(wall / audio_len, 4) if audio_len else None,
    "segments": segments,
    "feed_file": feed_file,
    "run_id": run_id,
    "feed_run_end_status": status,
    "peak_rss_mb": round(peak_kb / 1024.0, 1),
    "recorder_exit_code": int(rec_rc) if rec_rc != "" else None,
    "recorder": recorder,
}
with open(os.path.join(outdir, "result.json"), "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

rec = recorder or {}
lat = rec.get("latency_ms") or {}
longt = rec.get("longtasks") or {}
fps = rec.get("fps") or {}
columns = [
    ("when", time.strftime("%Y-%m-%dT%H:%M:%S")), ("audio", audio), ("model", model),
    ("extra_args", " ".join(extra)), ("exit", cli_rc), ("wall_s", f"{wall:.3f}"),
    ("audio_s", "" if audio_len is None else f"{audio_len:.2f}"),
    ("rtf", result["rtf"] if result["rtf"] is not None else ""),
    ("segments", "" if segments is None else segments), ("peak_rss_mb", result["peak_rss_mb"]),
    ("latency_median_ms", lat.get("median", "")), ("latency_p95_ms", lat.get("p95", "")),
    ("latency_max_ms", lat.get("max", "")), ("reconnects", rec.get("reconnects", "")),
    ("longtasks", longt.get("count", "")), ("fps_median", fps.get("median", "")),
    ("dom_segment_count", rec.get("dom_segment_count", "")), ("console_errors", rec.get("console_errors", "")),
    ("final_status", rec.get("final_status", "")), ("run_id", run_id or ""), ("outdir", outdir),
]
header = "\t".join(name for name, _ in columns)
new_file = not os.path.exists(results_tsv)
with open(results_tsv, "a", encoding="utf-8") as fh:
    if new_file or os.path.getsize(results_tsv) == 0:
        fh.write(header + "\n")
    fh.write("\t".join(str(value).replace("\t", " ").replace("\n", " ") for _, value in columns) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
then
  # Last resort: the full writer crashed, so still leave a result.json for this run.
  echo "run_real: result writer failed; writing a minimal result.json (no results.tsv row)" >&2
  /usr/bin/python3 -I -c '
import json, sys
outdir, audio, model, cli_rc, wall_s = sys.argv[1:6]
result = {"audio": audio, "model": model, "exit_code": cli_rc, "wall_s": wall_s, "audio_s": None,
          "rtf": None, "error": "result writer failed; see cli.log"}
with open(outdir + "/result.json", "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
' "$OUTDIR" "$AUDIO" "$MODEL" "$CLI_RC" "$WALL_S" || true
fi
