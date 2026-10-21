#!/usr/bin/env bash
# noScribe Live viewer: prepares the Python environment, builds the frontend when it is missing
# or its sources changed since the last build, and serves the viewer at http://localhost:8765.
# Works from any directory.
#
# Usage: live/run.sh [--rebuild]
#   --rebuild          rebuild live/web even if its build is up to date. Without it, run.sh still
#                      rebuilds by itself when live/web's sources changed (e.g. after git pull).
#
# Environment:
#   PORT=8765          port to serve on
#   HOST=127.0.0.1     address to bind (0.0.0.0 to listen on all interfaces)
#   LIVE_TOKEN=...     require this token on every path (empty: no gate). Not put on the command line;
#                      the server reads it from the environment, which exec passes on.
#   SKIP_WEB_BUILD=1   never run pnpm/npm in live/web; serve whatever is in live/web/dist
#   NOSCRIBE_PY=...    Python with noScribe installed; only used in the command this script prints
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: live/run.sh [--rebuild]

  --rebuild          rebuild the frontend in live/web even if its build is up to date.
                     Without it, run.sh rebuilds by itself when the sources changed since the last build.

Environment: PORT (default 8765), HOST (default 127.0.0.1), LIVE_TOKEN (optional token gate),
             SKIP_WEB_BUILD=1, NOSCRIBE_PY=/path/to/python
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
HOST="${HOST:-127.0.0.1}"
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

# Fingerprint of the frontend sources in live/web, printed on stdout. It is a content hash, not
# mtimes: a git pull that changes a file changes it, a bare touch does not. run.sh stores it in
# live/web/dist/.build-stamp after a successful build and compares it on the next start. With git,
# the inputs are the tracked files and the untracked files that are not ignored, under live/web
# (without dist and node_modules). Without git, they are the usual inputs of the build.
web_fingerprint() {
  (
    cd "$WEB_DIR" || exit 1
    manifest=""
    if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      # git hash-object works from the top of the work tree, so it gets paths as $rel$name
      rel="$(git rev-parse --show-prefix)"
      present=""
      feed=""
      while IFS= read -r -d '' f; do
        if [ -f "$f" ]; then
          present="$present$f"$'\n'
          feed="$feed$rel$f"$'\n'
        else
          manifest="$manifest$f MISSING"$'\n'   # a tracked file deleted from disk still counts
        fi
      done < <(git ls-files -z -- . ':(exclude)dist' ':(exclude)node_modules'
               git ls-files -z -o --exclude-standard -- . ':(exclude)dist' ':(exclude)node_modules')
      # --stdin-paths prints one hash per input line, in the same order as the input
      hashes="$(printf '%s' "$feed" | git hash-object --stdin-paths)"
      manifest="$manifest$(paste -d' ' <(printf '%s' "$present") <(printf '%s\n' "$hashes"))"
      printf '%s\n' "$manifest" | LC_ALL=C sort | git hash-object --stdin
    else
      if command -v shasum >/dev/null 2>&1; then
        hash_cmd="shasum -a 256"
      elif command -v sha256sum >/dev/null 2>&1; then
        hash_cmd="sha256sum"
      else
        hash_cmd="cksum"
      fi
      files="$(
        for f in package.json pnpm-lock.yaml package-lock.json index.html vite.config.* tsconfig*.json components.json; do
          if [ -f "$f" ]; then printf '%s\n' "$f"; fi
        done
        find src public -type f 2>/dev/null || true
      )"
      while IFS= read -r f; do
        if [ -n "$f" ]; then
          manifest="$manifest$f $($hash_cmd < "$f" | awk '{print $1}')"$'\n'
        fi
      done <<< "$(printf '%s\n' "$files" | LC_ALL=C sort -u)"
      printf '%s\n' "$manifest" | LC_ALL=C sort | $hash_cmd | awk '{print $1}'
    fi
  )
}

# 3. Frontend: built with pnpm (npm if pnpm is missing) when live/web has a package.json and the
#    build is missing, stale (its sources changed since the last build) or forced with --rebuild.
WEB_STAMP="$WEB_DIR/dist/.build-stamp"
if [ "${SKIP_WEB_BUILD:-0}" = "1" ]; then
  echo "run.sh: SKIP_WEB_BUILD=1, leaving $WEB_DIR alone"
elif [ -f "$WEB_DIR/package.json" ]; then
  WEB_FP="$(web_fingerprint)"
  build_reason=""
  if [ "$REBUILD" -eq 1 ]; then
    build_reason="run.sh: rebuilding the frontend (--rebuild)"
  elif [ ! -f "$WEB_DIR/dist/index.html" ]; then
    build_reason="run.sh: building the frontend (no build yet)"
  elif [ ! -f "$WEB_STAMP" ]; then
    build_reason="run.sh: rebuilding the frontend (the existing build has no source stamp)"
  elif [ "$(cat "$WEB_STAMP")" != "$WEB_FP" ]; then
    build_reason="run.sh: rebuilding the frontend (its sources changed since the last build)"
  else
    echo "run.sh: the frontend build is up to date"
  fi
  if [ -n "$build_reason" ]; then
    echo "$build_reason"
    (
      cd "$WEB_DIR"
      if command -v pnpm >/dev/null 2>&1; then
        pnpm install --frozen-lockfile || pnpm install
        pnpm build
      elif command -v npm >/dev/null 2>&1; then
        # --no-package-lock: npm must not write live/web/package-lock.json (the project locks with pnpm)
        npm install --no-package-lock
        npm run build
      else
        echo "run.sh: neither pnpm nor npm is installed; cannot build the frontend" >&2
        exit 1
      fi
    )
    # Written only after a successful build (set -e exits above on failure). The fingerprint is taken
    # after the build because pnpm install may have updated pnpm-lock.yaml, which is part of it.
    printf '%s\n' "$(web_fingerprint)" > "$WEB_STAMP"
  fi
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
exec "$VENV_PY" -m server --feeds "$LIVE_DIR/feeds" --static "$LIVE_DIR/web/dist" --host "$HOST" --port "$PORT"
