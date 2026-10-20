#!/usr/bin/env bash
# noScribe Live: keeps a localhost.run SSH reverse tunnel up for a local viewer port and records
# the current public URL in live/logs/tunnel-url.txt (override with URL_FILE=...), also on stdout.
#
# Usage: live/stress/tunnel.sh [PORT]     (PORT defaults to 8766, the gated viewer)
# Stop:  send TERM to the script. It kills its ssh child and exits.
#
# THE URL CHANGES ON EVERY RECONNECT. Anonymous localhost.run tunnels get a new *.lhr.life
# subdomain each time ssh connects. After an "ssh exited" line, wait for the next "url" line
# (or re-read live/logs/tunnel-url.txt) before sharing the link. While the tunnel is down,
# the file still holds the last URL.
#
# Why not Cloudflare: trycloudflare quick tunnels were tried first, but they do not stream
# Server-Sent Events (verified: 200 with 0 bytes after 25 s), and this viewer needs SSE.
# localhost.run is plain SSH with no account, so it streams fine.
#
# Key: $REPO/.tools/ssh/id_ed25519, created with ssh-keygen if missing. known_hosts is kept in
# $REPO/.tools/ssh/. Both are git-ignored.
# Backoff after ssh exits: 5 s, doubling to a 60 s cap. A connection that lasted more than
# 5 min resets the backoff to 5 s.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${1:-8766}"
URL_FILE="${URL_FILE:-$REPO/live/logs/tunnel-url.txt}"
KEY="$REPO/.tools/ssh/id_ed25519"
KNOWN_HOSTS="$REPO/.tools/ssh/known_hosts"
URL_RE='https://[a-z0-9-]+\.lhr\.life'
MIN_BACKOFF=5
MAX_BACKOFF=60
STABLE_SECS=300

case "$PORT" in
  '' | *[!0-9]*)
    echo "usage: $0 [PORT]" >&2
    exit 2
    ;;
esac

ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

mkdir -p "$REPO/.tools/ssh" "$(dirname "$URL_FILE")" || exit 1
if [ ! -f "$KEY" ]; then
  echo "$(ts) no key at $KEY, generating one"
  ssh-keygen -q -t ed25519 -N '' -f "$KEY" || exit 1
fi

# ssh writes its stdout into a FIFO so this shell can read it line by line and still know the ssh pid.
FIFO_DIR="$(mktemp -d)" || exit 1
FIFO="$FIFO_DIR/ssh-stdout"
mkfifo "$FIFO" || exit 1
SSH_PID=""
SLEEP_PID=""

cleanup() {
  if [ -n "$SSH_PID" ]; then kill "$SSH_PID" 2>/dev/null; fi
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

echo "$(ts) tunnel 127.0.0.1:$PORT via localhost.run, url file $URL_FILE"
delay=$MIN_BACKOFF
while true; do
  start=$(date +%s)
  ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
    -T -R "80:127.0.0.1:$PORT" nokey@localhost.run >"$FIFO" &
  SSH_PID=$!
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ $line =~ $URL_RE ]]; then
      url="${BASH_REMATCH[0]}"
      printf '%s\n' "$url" >"$URL_FILE"
      echo "$(ts) url $url"
    fi
  done <"$FIFO"
  wait "$SSH_PID"
  rc=$?
  SSH_PID=""
  if [ $(( $(date +%s) - start )) -gt "$STABLE_SECS" ]; then
    delay=$MIN_BACKOFF
  fi
  echo "$(ts) ssh exited rc=$rc, reconnecting in ${delay}s"
  sleep "$delay" &
  SLEEP_PID=$!
  wait "$SLEEP_PID"
  SLEEP_PID=""
  delay=$(( delay * 2 ))
  if [ "$delay" -gt "$MAX_BACKOFF" ]; then delay=$MAX_BACKOFF; fi
done
