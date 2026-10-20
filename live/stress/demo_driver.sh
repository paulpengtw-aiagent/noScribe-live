#!/usr/bin/env bash
# Keeps noScribe Live busy for a while: a real noScribe run when the GPU and memory allow it
# (otherwise a replay instead), a pause, a replay of a finished feed, a pause, and so on.
#
# Usage: live/stress/demo_driver.sh     (any directory; stop it with TERM or INT)
#
# Environment:
#   DURATION_S=7200                 keep going this long
#   GAP_S=60                        pause after each step
#   CLIPS="live/samples/stress/01-demo-en-zh.mp3 ..."
#                                   clips for real runs, relative to the repo root; missing files are skipped
#   MODEL=breeze-asr-25             Whisper model for real runs
#   NOSCRIBE_PY=/home/cheng/noScribe/venv/bin/python
#   FEEDS_DIR=live/feeds            feed directory the viewer reads (real runs write here, replays read and write here)
#   MIN_FREE_BYTES=4294967296       free memory needed to start a real run (4 GiB)
#   RUN_TIMEOUT_S=900               a real run is killed after this long
#   KILL_EVERY=3                    fault injection (below) every this many cycles
#   KILL_MIN_INTERVAL_S=3600        ... and at most once per this many seconds (the schedule is once per hour)
#   KILL_AFTER_S=35                 the killed run's CLI gets SIGKILL after this long
#   KILL_CLIP=live/samples/stress/03-multi-speaker.mp3   clip for the killed run (same guards as a real run)
#   FAIL_CLIP=live/samples/stress/90-corrupt.mp3         clip for the failed run (fails in ~2 s, no GPU)
#
# Fault injection, when due: (a) a killed run: a real run, SIGKILL to the CLI after KILL_AFTER_S, with its
# multiprocessing children (found with pgrep -P before the kill) killed too; (b) a failed run: the CLI on the
# corrupt clip. Both write their feeds to FEEDS_DIR like any other run.
#
# Every step is logged with a timestamp to live/logs/driver.log.
set -uo pipefail

STRESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_DIR="$(cd "$STRESS_DIR/.." && pwd)"
REPO_ROOT="$(cd "$LIVE_DIR/.." && pwd)"
DURATION_S="${DURATION_S:-7200}"
GAP_S="${GAP_S:-60}"
CLIPS="${CLIPS:-live/samples/stress/01-demo-en-zh.mp3 live/samples/stress/02-zh-tw-speech.mp3 live/samples/stress/03-multi-speaker.mp3 live/samples/stress/04-codeswitch-zh-en.mp3}"
MODEL="${MODEL:-breeze-asr-25}"
NOSCRIBE_PY="${NOSCRIBE_PY:-/home/cheng/noScribe/venv/bin/python}"
FEEDS_DIR="${FEEDS_DIR:-live/feeds}"
MIN_FREE_BYTES="${MIN_FREE_BYTES:-4294967296}"
RUN_TIMEOUT_S="${RUN_TIMEOUT_S:-900}"
KILL_EVERY="${KILL_EVERY:-3}"
KILL_MIN_INTERVAL_S="${KILL_MIN_INTERVAL_S:-3600}"
KILL_AFTER_S="${KILL_AFTER_S:-35}"
KILL_CLIP="${KILL_CLIP:-live/samples/stress/03-multi-speaker.mp3}"
FAIL_CLIP="${FAIL_CLIP:-live/samples/stress/90-corrupt.mp3}"
FAULT_CYCLE=0
FAULT_LAST_CYCLE=0
FAULT_LAST_TIME=0
OUT_DIR=/tmp/nslive-driver
LOG="$LIVE_DIR/logs/driver.log"
CLIP_INDEX=0
CHILD=""

case "$FEEDS_DIR" in
  /*) ;;
  *) FEEDS_DIR="$REPO_ROOT/$FEEDS_DIR" ;;
esac
read -r -a CLIP_LIST <<< "$CLIPS"

log() {
  mkdir -p "$(dirname "$LOG")"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"
}

cleanup() {
  log "driver stopping on signal"
  if [ -n "$CHILD" ]; then
    kill -TERM "$CHILD" 2>/dev/null
    wait "$CHILD" 2>/dev/null
  fi
  exit 0
}
trap cleanup TERM INT

# Runs a command in the background so that a signal can interrupt the wait. Sets STATUS.
run_child() {
  "$@" &
  CHILD=$!
  wait "$CHILD"
  STATUS=$?
  CHILD=""
}

pause() {
  run_child sleep "$GAP_S"
}

# Free memory in bytes: memory.max - memory.current + inactive_file (cgroup v2), or MemAvailable without a limit.
free_bytes() {
  local max current inactive
  max=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
  current=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
  inactive=$(awk '$1 == "inactive_file" {print $2}' /sys/fs/cgroup/memory.stat 2>/dev/null)
  if [ "$max" = "max" ]; then
    awk '/^MemAvailable:/ {print $2 * 1024}' /proc/meminfo
    return
  fi
  echo $(( max - current + ${inactive:-0} ))
}

# Prints why a real run must not start and returns 0; prints nothing and returns 1 when it may start.
real_run_blocker() {
  local free users
  free=$(free_bytes)
  if [ -z "$free" ] || [ "$free" -lt "$MIN_FREE_BYTES" ]; then
    echo "free memory ${free:-unknown} bytes is below $MIN_FREE_BYTES"
    return 0
  fi
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi is not installed"
    return 0
  fi
  if ! users=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); then
    echo "nvidia-smi failed"
    return 0
  fi
  users=$(printf '%s' "$users" | tr -s ' \n' ' ' | sed 's/^ *//; s/ *$//')
  if [ -n "$users" ]; then
    echo "GPU is in use by compute pid(s): $users"
    return 0
  fi
  return 1
}

# Sets CLIP to the next clip that exists (round robin); returns 1 when none exists.
next_clip() {
  local n=${#CLIP_LIST[@]} i idx path
  for ((i = 0; i < n; i++)); do
    idx=$(( (CLIP_INDEX + i) % n ))
    case "${CLIP_LIST[idx]}" in
      /*) path="${CLIP_LIST[idx]}" ;;
      *) path="$REPO_ROOT/${CLIP_LIST[idx]}" ;;
    esac
    if [ -f "$path" ]; then
      CLIP="$path"
      CLIP_INDEX=$(( idx + 1 ))
      return 0
    fi
  done
  return 1
}

real_run() {
  local clip="$1" stem out
  stem="$(basename "$clip")"
  stem="${stem%.*}-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$OUT_DIR"
  out="$OUT_DIR/$stem.html"
  log "start real run clip=$clip model=$MODEL output=$out"
  cd "$REPO_ROOT" || return 1
  run_child env PYTHONDONTWRITEBYTECODE=1 timeout --kill-after=30 "$RUN_TIMEOUT_S" \
    "$NOSCRIBE_PY" -m noScribe --no-gui --model "$MODEL" --speaker-detection auto --timestamps \
    --live-feed "$FEEDS_DIR/" "$clip" "$out"
  local note=""
  [ "$STATUS" -eq 124 ] && note=" (killed after ${RUN_TIMEOUT_S}s)"
  log "end real run clip=$clip exit=$STATUS$note"
}

# The newest finished feed that is not a replay; otherwise the newest feed of any kind.
latest_feed() {
  local f
  local -a files
  mapfile -t files < <(ls -1t "$FEEDS_DIR"/*.ndjson 2>/dev/null)
  for f in "${files[@]}"; do
    case "$(basename "$f")" in replay-*) continue ;; esac
    if grep -q '"type": *"run_end"' "$f"; then
      echo "$f"
      return 0
    fi
  done
  if [ "${#files[@]}" -gt 0 ]; then
    echo "${files[0]}"
    return 0
  fi
  return 1
}

replay() {
  local feed
  if ! feed="$(latest_feed)"; then
    log "skip replay: no feed in $FEEDS_DIR"
    return 0
  fi
  log "start replay feed=$feed"
  cd "$LIVE_DIR" || return 1
  run_child .venv/bin/python -m server.replay "$feed" --feeds "$FEEDS_DIR" --speed 1 --max-gap 5
  log "end replay feed=$feed exit=$STATUS"
}

# Killed run: a real run on KILL_CLIP with the same guards as real_run; SIGKILL to the CLI after KILL_AFTER_S.
# The CLI's multiprocessing children are listed with pgrep -P before the kill, since they would be orphaned
# (re-parented) once the CLI dies; they are SIGKILLed too.
# True while the process runs (a zombie, exited but not yet waited for, counts as gone).
alive() {
  local state
  state=$(awk '/^State:/ {print $2}' "/proc/$1/status" 2>/dev/null)
  [ -n "$state" ] && [ "$state" != "Z" ]
}

killed_run() {
  local clip="$KILL_CLIP" reason cli out status kids="" waited=0 k
  case "$clip" in
    /*) ;;
    *) clip="$REPO_ROOT/$clip" ;;
  esac
  if [ ! -f "$clip" ]; then
    log "skip killed run: $clip does not exist"
    return 0
  fi
  if reason="$(real_run_blocker)"; then
    log "skip killed run: $reason"
    return 0
  fi
  mkdir -p "$OUT_DIR"
  out="$OUT_DIR/killed-$(date +%Y%m%d-%H%M%S).html"
  log "start killed run clip=$clip model=$MODEL output=$out (SIGKILL after ${KILL_AFTER_S}s)"
  cd "$REPO_ROOT" || return 1
  env PYTHONDONTWRITEBYTECODE=1 "$NOSCRIBE_PY" -m noScribe --no-gui --model "$MODEL" \
    --speaker-detection auto --timestamps --live-feed "$FEEDS_DIR/" "$clip" "$out" &
  cli=$!
  CHILD="$cli"
  while [ "$waited" -lt "$KILL_AFTER_S" ] && alive "$cli"; do
    sleep 1
    waited=$(( waited + 1 ))
  done
  if alive "$cli"; then
    kids="$(pgrep -P "$cli" -f multiprocessing 2>/dev/null | tr '\n' ' ')"
    log "killed run: SIGKILL to cli pid=$cli after ${waited}s; multiprocessing children: ${kids:-none}"
    kill -KILL "$cli" 2>/dev/null
    for k in $kids; do
      kill -KILL "$k" 2>/dev/null
    done
  else
    log "killed run: cli pid=$cli exited before the kill"
  fi
  wait "$cli" 2>/dev/null
  status=$?
  CHILD=""
  log "end killed run clip=$clip exit=$status"
}

# Failed run: the CLI on the corrupt clip. It fails in about 2 s and needs no GPU, so no GPU guard.
failed_run() {
  local clip="$FAIL_CLIP" out
  case "$clip" in
    /*) ;;
    *) clip="$REPO_ROOT/$clip" ;;
  esac
  if [ ! -f "$clip" ]; then
    log "skip failed run: $clip does not exist"
    return 0
  fi
  mkdir -p "$OUT_DIR"
  out="$OUT_DIR/failed-$(date +%Y%m%d-%H%M%S).html"
  log "start failed run clip=$clip (expected to fail in about 2 s)"
  cd "$REPO_ROOT" || return 1
  run_child env PYTHONDONTWRITEBYTECODE=1 timeout --kill-after=30 "$RUN_TIMEOUT_S" \
    "$NOSCRIBE_PY" -m noScribe --no-gui --model "$MODEL" --speaker-detection auto --timestamps \
    --live-feed "$FEEDS_DIR/" "$clip" "$out"
  log "end failed run clip=$clip exit=$STATUS"
}

# Due when KILL_EVERY cycles have passed since the last injection and KILL_MIN_INTERVAL_S seconds too.
fault_due() {
  [ $(( FAULT_CYCLE - FAULT_LAST_CYCLE )) -ge "$KILL_EVERY" ] &&
    [ $(( $(date +%s) - FAULT_LAST_TIME )) -ge "$KILL_MIN_INTERVAL_S" ]
}

fault_injection() {
  FAULT_LAST_CYCLE=$FAULT_CYCLE
  FAULT_LAST_TIME=$(date +%s)
  log "fault injection at cycle $FAULT_CYCLE: killed run, then failed run"
  killed_run
  pause
  failed_run
}

DEADLINE=$(( $(date +%s) + DURATION_S ))
log "driver start duration=${DURATION_S}s gap=${GAP_S}s feeds=$FEEDS_DIR clips=\"$CLIPS\" kill_every=${KILL_EVERY} cycles, min interval ${KILL_MIN_INTERVAL_S}s"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  FAULT_CYCLE=$(( FAULT_CYCLE + 1 ))
  if fault_due; then
    fault_injection
  fi
  if ! next_clip; then
    log "skip real run: no clip in \"$CLIPS\" exists"
    replay
  elif reason="$(real_run_blocker)"; then
    log "skip real run: $reason"
    replay
  else
    real_run "$CLIP"
  fi
  pause
  replay
  pause
done
log "driver finished at the deadline"
