#!/usr/bin/env bash
# noScribe Live viewer: prepares the Python environment, builds the frontend when it is
# missing, and serves the viewer at http://localhost:8765. Works from any directory.
#
# Usage: live/run.sh [--rebuild]
#   --rebuild          rebuild live/web even if live/web/dist already exists
#
# Environment:
#   PORT=8765          port to serve on
#   SKIP_WEB_BUILD=1   never run pnpm/npm in live/web; serve whatever is in live/web/dist
#   NOSCRIBE_PY=...    Python with noScribe installed; only used in the command this script prints
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: live/run.sh [--rebuild]

  --rebuild          rebuild the frontend in live/web even if live/web/dist exists

Environment: PORT (default 8765), SKIP_WEB_BUILD=1, NOSCRIBE_PY=/path/to/python
EOF
}

LIVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIVE_DIR/.." && pwd)"
VENV_DIR="$LIVE_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
REQ_FILE="$LIVE_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.req-stamp"
WEB_DIR="$LIVE_DIR/web"
PORT="${PORT:-8765}"
REBUILD=0

for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "run.sh: unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# uv is preferred: it is fast and can provide Python 3.11. Otherwise use the stdlib venv module.
UV_BIN=""
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
fi

# 1. Virtualenv in live/.venv
if [ ! -x "$VENV_PY" ]; then
  echo "run.sh: creating $VENV_DIR"
  created=0
  if [ -n "$UV_BIN" ] && "$UV_BIN" venv --python 3.11 "$VENV_DIR"; then
    created=1
  fi
  if [ "$created" -eq 0 ]; then
    if [ -n "$UV_BIN" ]; then
      echo "run.sh: uv could not create a Python 3.11 venv; falling back to python3 -m venv" >&2
    fi
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
fi

# 2. Dependencies, installed only when requirements.txt is newer than the last install
if [ ! -f "$REQ_STAMP" ] || [ "$REQ_FILE" -nt "$REQ_STAMP" ]; then
  echo "run.sh: installing $REQ_FILE"
  if [ -n "$UV_BIN" ]; then
    "$UV_BIN" pip install --python "$VENV_PY" -r "$REQ_FILE"
  else
    "$VENV_PY" -m pip install --quiet -r "$REQ_FILE"
  fi
  touch "$REQ_STAMP"
fi

# 3. Frontend: built with pnpm (npm if pnpm is missing) when live/web has a package.json
#    and there is no build yet, or when --rebuild was given.
if [ "${SKIP_WEB_BUILD:-0}" = "1" ]; then
  echo "run.sh: SKIP_WEB_BUILD=1, leaving $WEB_DIR alone"
elif [ -f "$WEB_DIR/package.json" ] && { [ ! -f "$WEB_DIR/dist/index.html" ] || [ "$REBUILD" -eq 1 ]; }; then
  echo "run.sh: building the frontend in $WEB_DIR"
  (
    cd "$WEB_DIR"
    if command -v pnpm >/dev/null 2>&1; then
      pnpm install --frozen-lockfile || pnpm install
      pnpm build
    elif command -v npm >/dev/null 2>&1; then
      npm ci || npm install
      npm run build
    else
      echo "run.sh: neither pnpm nor npm is installed; cannot build the frontend" >&2
      exit 1
    fi
  )
fi

if [ -f "$WEB_DIR/dist/index.html" ]; then
  echo "run.sh: serving the built frontend in $WEB_DIR/dist"
else
  echo "run.sh: no built frontend in $WEB_DIR/dist; the server will show a placeholder page"
fi

mkdir -p "$LIVE_DIR/feeds"

cat <<EOF

  noScribe Live viewer:  http://localhost:$PORT

  Feeds are read from:   $LIVE_DIR/feeds

  To transcribe with live output, run this from the repo root ($REPO_ROOT) in
  another terminal. Any Python environment with noScribe installed works; set
  NOSCRIBE_PY=/path/to/python to override the interpreter:

    PYTHONDONTWRITEBYTECODE=1 ${NOSCRIBE_PY:-/home/cheng/noScribe/venv/bin/python} -m noScribe --no-gui --model breeze-asr-25 --speaker-detection auto --timestamps --live-feed live/feeds/ INPUT OUTPUT.html

EOF

# exec replaces this shell, so the PID you background is the server's PID.
cd "$LIVE_DIR"
exec "$VENV_PY" -m server --feeds "$LIVE_DIR/feeds" --static "$LIVE_DIR/web/dist" --port "$PORT"
