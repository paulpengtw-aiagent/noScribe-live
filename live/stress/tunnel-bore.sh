#!/usr/bin/env bash
# noScribe Live: keeps a bore.pub TCP tunnel up for a local viewer port on a FIXED remote port, so the
# public URL stays the same across reconnects. Writes http://bore.pub:N to URL_FILE (default
# live/logs/tunnel-url.txt) and logs the same URL on stdout.
#
# Usage: live/stress/tunnel-bore.sh [LOCAL_PORT] [REMOTE_PORT]
#   LOCAL_PORT   defaults to 8766, the gated viewer.
#   REMOTE_PORT  defaults to the port in PORT_FILE (default live/logs/bore-port). If that file does not
#                exist, a random port in 20000-60000 is picked once and saved there. An explicit
#                REMOTE_PORT is used and saved too, so later runs without it keep the same URL.
# Stop:  send TERM to the script. It kills its probe and its bore child, then exits.
# Env:   BORE (default $REPO/.tools/bore), URL_FILE, PORT_FILE, PROBE_S (default 60).
# Dead-tunnel check: a background probe curls $URL/ every PROBE_S seconds (curl -m 15). Any HTTP
# response, whatever the status, counts as alive; no response (refused, timeout, reset) counts as a
# failure. After 2 failures in a row the bore child is killed and the main loop reconnects to the same
# remote port.
#
# Why bore: Cloudflare quick tunnels return 200 but 0 bytes for /api/stream, even with a 2 KB pad and
# no-transform. localhost.run's free tier rotates its URL about every 20 min.
#
# PLAIN HTTP: bore is TCP forwarding with no TLS. The token and the cookie travel unencrypted between
# the browser and bore.pub. Use it for public test audio only.
#
# Backoff after bore exits: 5 s, doubling to a 60 s cap. A connection that lasted more than 5 min
# resets the backoff to 5 s. If bore reports the remote port is in use 3 times in a row, a warning is
# logged and the SAME port is retried, so the URL never changes silently.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_PORT="${1:-8766}"
BORE="${BORE:-$REPO/.tools/bore}"
URL_FILE="${URL_FILE:-$REPO/live/logs/tunnel-url.txt}"
PORT_FILE="${PORT_FILE:-$REPO/live/logs/bore-port}"
URL_RE='listening at bore\.pub:([0-9]+)'
BUSY_RE='port.*(in use|unavailable)'
PORT_RE='^[0-9]{2,5}$'
MIN_BACKOFF=5
MAX_BACKOFF=60
STABLE_SECS=300
BUSY_WARN_AT=3

ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

case "$LOCAL_PORT" in
  '' | *[!0-9]*)
    echo "usage: $0 [LOCAL_PORT] [REMOTE_PORT]" >&2
    exit 2
    ;;
esac
case "${2:-}" in
  *[!0-9]*)
    echo "usage: $0 [LOCAL_PORT] [REMOTE_PORT]" >&2
    exit 2
    ;;
esac

PROBE_S="${PROBE_S:-60}"
case "$PROBE_S" in
  '' | *[!0-9]* | 0)
    echo "PROBE_S must be a positive number of seconds, got '$PROBE_S'" >&2
    exit 2
    ;;
esac

if [ ! -x "$BORE" ]; then
  echo "$(ts) bore binary not found or not executable at $BORE" >&2
  echo "  download the static musl build from https://github.com/ekzhang/bore/releases into $REPO/.tools/ (or set BORE)" >&2
  exit 1
fi

mkdir -p "$(dirname "$URL_FILE")" "$(dirname "$PORT_FILE")" || exit 1
if [ -n "${2:-}" ]; then
  REMOTE_PORT="$2"
  printf '%s\n' "$REMOTE_PORT" >"$PORT_FILE"
elif [ -s "$PORT_FILE" ] && [[ $(<"$PORT_FILE") =~ $PORT_RE ]]; then
  REMOTE_PORT="$(<"$PORT_FILE")"
else
  REMOTE_PORT=$(( 20000 + (RANDOM * 32768 + RANDOM) % 40001 ))
  printf '%s\n' "$REMOTE_PORT" >"$PORT_FILE"
  echo "$(ts) picked remote port $REMOTE_PORT, saved in $PORT_FILE"
fi

# bore writes its output into a FIFO so this shell can read it line by line and still know the bore pid.
FIFO_DIR="$(mktemp -d)" || exit 1
FIFO="$FIFO_DIR/bore-stdout"
mkfifo "$FIFO" || exit 1
BORE_PID=""
SLEEP_PID=""
PROBE_PID=""
PROBE_TIMEOUT=15
PROBE_FAILS_MAX=2

cleanup() {
  if [ -n "$PROBE_PID" ]; then kill "$PROBE_PID" 2>/dev/null; fi
  if [ -n "$BORE_PID" ]; then kill "$BORE_PID" 2>/dev/null; fi
  if [ -n "$SLEEP_PID" ]; then kill "$SLEEP_PID" 2>/dev/null; fi
  rm -rf "$FIFO_DIR"
}
on_signal() {
  echo "$(ts) signal received, stopping"
  cleanup
  exit 0
}
trap on_signal TERM INT
trap cleanup EXIT

echo "$(ts) tunnel 127.0.0.1:$LOCAL_PORT via bore.pub on remote port $REMOTE_PORT, url file $URL_FILE"

# Runs as a background subshell. It reads the public URL from URL_FILE on every probe and the bore
# child's pid from $FIFO_DIR/bore.pid, which the main loop keeps up to date.
probe_loop() {
  trap - EXIT
  local fails=0 url rc bore_pid
  child=""
  trap 'if [ -n "$child" ]; then kill "$child" 2>/dev/null; fi; exit 0' TERM INT
  while true; do
    sleep "$PROBE_S" &
    child=$!
    wait "$child"
    child=""
    url="$(head -n 1 "$URL_FILE" 2>/dev/null)"
    if [ -z "$url" ]; then continue; fi
    curl -s -o /dev/null -m "$PROBE_TIMEOUT" "$url/" &
    child=$!
    wait "$child"
    rc=$?
    child=""
    if [ "$rc" -eq 0 ]; then
      fails=0
      continue
    fi
    fails=$(( fails + 1 ))
    echo "$(ts) probe $url failed ($fails in a row, curl rc=$rc)"
    if [ "$fails" -ge "$PROBE_FAILS_MAX" ]; then
      echo "$(ts) public URL unreachable twice; restarting the bore client"
      fails=0
      if [ -s "$FIFO_DIR/bore.pid" ]; then
        bore_pid="$(<"$FIFO_DIR/bore.pid")"
        # TERM, then CONT: a stopped bore child still dies, since the pending TERM is delivered on resume.
        kill -TERM "$bore_pid" 2>/dev/null
        kill -CONT "$bore_pid" 2>/dev/null
      fi
    fi
  done
}
probe_loop &
PROBE_PID=$!
echo "$(ts) probing $URL_FILE every ${PROBE_S}s"
delay=$MIN_BACKOFF
busy_streak=0
while true; do
  start=$(date +%s)
  busy=0
  connected=0
  "$BORE" local "$LOCAL_PORT" --to bore.pub --port "$REMOTE_PORT" >"$FIFO" 2>&1 &
  BORE_PID=$!
  printf '%s\n' "$BORE_PID" >"$FIFO_DIR/bore.pid"
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ $line =~ $URL_RE ]]; then
      connected=1
      url="http://bore.pub:${BASH_REMATCH[1]}"
      printf '%s\n' "$url" >"$URL_FILE"
      echo "$(ts) url $url"
    else
      echo "$(ts) bore: $line"
      if [[ ${line,,} =~ $BUSY_RE ]]; then busy=1; fi
    fi
  done <"$FIFO"
  wait "$BORE_PID"
  rc=$?
  BORE_PID=""
  rm -f "$FIFO_DIR/bore.pid"
  if [ $(( $(date +%s) - start )) -gt "$STABLE_SECS" ]; then
    delay=$MIN_BACKOFF
  fi
  if [ "$connected" = 1 ] || [ "$busy" = 0 ]; then
    busy_streak=0
  else
    busy_streak=$(( busy_streak + 1 ))
  fi
  if [ "$busy_streak" -ge "$BUSY_WARN_AT" ]; then
    echo "$(ts) WARNING: remote port $REMOTE_PORT is in use on bore.pub ($busy_streak failed attempts in a row); retrying the SAME port, the URL stays http://bore.pub:$REMOTE_PORT"
  fi
  echo "$(ts) bore exited rc=$rc, reconnecting in ${delay}s"
  sleep "$delay" &
  SLEEP_PID=$!
  wait "$SLEEP_PID"
  SLEEP_PID=""
  delay=$(( delay * 2 ))
  if [ "$delay" -gt "$MAX_BACKOFF" ]; then delay=$MAX_BACKOFF; fi
done
