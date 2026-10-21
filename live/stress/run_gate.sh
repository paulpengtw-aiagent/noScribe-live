#!/usr/bin/env bash
# UI gate for noScribe Live. Runs the stress steps one at a time, each in its own session and
# process group, so a timeout takes the whole tree down (Playwright, chromium, and any server or
# replay the test started).
#
#   live/stress/run_gate.sh [--out DIR] [--only step1,step2] [--dist DIR] [--timeout SECS]
#
# Steps, in order: ux-stick ux-reveal ux-conn ux-para ux-picker follow jump cjk r7 showreel nordic
#   i18n reconnect axe-matrix axe-preroll bundle
# Per step:
#   - timeout 420 s by default (--timeout changes the default); TIMEOUT_<STEP> in the environment
#     overrides one step (step name upper-cased, '-' becomes '_', e.g. TIMEOUT_AXE_MATRIX=900).
#     On timeout: kill -TERM -<pgid>, wait 5 s, kill -KILL -<pgid>. The group is also KILLed after
#     a normal exit, so nothing a test left running blocks the next step's ports.
#   - memory gate: while /sys/fs/cgroup/memory.current > MEM_MAX (bytes; default 18 GiB), poll every
#     15 s for at most 3 min, then SKIP the step.
# Output: OUT/<step>.log (stdout and stderr of the step), and one line per step in OUT/gate.log:
#   "<time> <step> rc=<rc> <last SUMMARY or RESULT line, or TIMEOUT>". A table is printed at the end.
# Exit: 0 only if every selected step passed; 1 otherwise; 2 on bad arguments.
# Steps run sequentially on purpose: they share ports 8769-8940 and the browser.
#
# Examples:
#   live/stress/run_gate.sh --out /tmp/gate-1
#   live/stress/run_gate.sh --only follow,jump --dist /workspace/noScribe-live-showreel/live/web/dist
#   TIMEOUT_AXE_MATRIX=900 live/stress/run_gate.sh --only axe-matrix,bundle

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$SCRIPT_DIR/../.." && pwd)
LIVE="$REPO/live"
PY=/usr/bin/python3
PY_CMD=("$PY" -I -B)
OUT="/tmp/nslive-gate-$(date +%Y%m%d-%H%M%S)"
DIST="$LIVE/web/dist"
ONLY=""
DEFAULT_TIMEOUT=420
MEM_MAX=${MEM_MAX:-19327352832}   # 18 GiB
MEM_POLL=15
MEM_WAIT_MAX=180
STEPS=(ux-stick ux-reveal ux-conn ux-para ux-picker follow jump cjk r7 showreel nordic i18n reconnect
       axe-matrix axe-preroll bundle)
CUR_PGID=""
CMD=()

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}"; }

while (($#)); do
  case "$1" in
    --out) OUT=${2:?--out needs a directory}; shift 2 ;;
    --only) ONLY=${2:?--only needs a step list}; shift 2 ;;
    --dist) DIST=${2:?--dist needs a directory}; shift 2 ;;
    --timeout) DEFAULT_TIMEOUT=${2:?--timeout needs seconds}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "run_gate.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

OUT=$(realpath -m -- "$OUT")
DIST=$(realpath -m -- "$DIST")
[[ -f "$DIST/index.html" ]] || { echo "run_gate.sh: no index.html in $DIST (use --dist)" >&2; exit 2; }
for s in $(tr ',' ' ' <<<"$ONLY"); do
  [[ " ${STEPS[*]} " == *" $s "* ]] || { echo "run_gate.sh: unknown step '$s' (steps: ${STEPS[*]})" >&2; exit 2; }
done
selected() { [[ -z $ONLY ]] || [[ ",$ONLY," == *",$1,"* ]]; }
mkdir -p "$OUT"

log_line() { printf '%s %s rc=%s %s\n' "$(date '+%F %T')" "$1" "$2" "$3" >>"$OUT/gate.log"; }

on_abort() {
  [[ -n $CUR_PGID ]] && kill -KILL -- "-$CUR_PGID" 2>/dev/null
  log_line "gate" "-" "ABORTED by signal, current step group killed"
  exit 130
}
trap on_abort INT TERM

# Python snippets (run with /usr/bin/python3 -I -B).
BUNDLE_PY=$(cat <<'PYEOF'
import gzip, os, sys
from html.parser import HTMLParser
LIMIT = 230000
dist = sys.argv[1]

class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.files = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type") == "module" and a.get("src"):
            self.files.append(a["src"])
        elif tag == "link" and "modulepreload" in (a.get("rel") or "").split() and a.get("href"):
            self.files.append(a["href"])

refs = Refs()
with open(os.path.join(dist, "index.html"), encoding="utf-8") as fh:
    refs.feed(fh.read())
total = 0
for ref in refs.files:
    path = os.path.join(dist, ref.split("?")[0].split("#")[0].lstrip("/"))
    with open(path, "rb") as fh:
        size = len(gzip.compress(fh.read(), compresslevel=6, mtime=0))
    total += size
    print(f"  {ref} gzip-6 {size}")
ok = bool(refs.files) and total <= LIMIT
print(f"RESULT bundle {'PASS' if ok else 'FAIL'} entry+modulepreload gzip-6 total {total} bytes "
      f"(limit {LIMIT}, {len(refs.files)} files)")
sys.exit(0 if ok else 1)
PYEOF
)

AXE_PY=$(cat <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        axe = json.load(fh).get("axe") or {}
except Exception as exc:
    print(f"SUMMARY axe-matrix: no readable summary.json ({exc.__class__.__name__})")
    sys.exit(1)
ok_entries = [e for e in axe.values() if "error" not in e]
errors = len(axe) - len(ok_entries)
def rules(impact):
    return sum((e.get("rules_by_impact") or {}).get(impact, 0) for e in ok_entries)
serious, critical = rules("serious"), rules("critical")
print(f"SUMMARY axe-matrix: configs={len(axe)} serious={serious} critical={critical} errors={errors}")
sys.exit(0 if axe and not errors and not serious and not critical else 1)
PYEOF
)

build_cmd() {  # sets CMD to the argv of step $1
  local step=$1 work="$OUT/work/$1" t="$SCRIPT_DIR"
  case "$step" in
    ux-stick|ux-reveal|ux-conn|ux-para|ux-picker)
      CMD=("${PY_CMD[@]}" "$t/test_ux.py" --only "${step#ux-}" --port 8770 --static "$DIST" --work "$work") ;;
    follow)     CMD=("${PY_CMD[@]}" "$t/test_follow.py" --static "$DIST" --port 8769 --work "$work") ;;
    jump)       CMD=("${PY_CMD[@]}" "$t/test_jump_label.py" --port 8911 --static "$DIST" --work "$work") ;;
    cjk)        CMD=("${PY_CMD[@]}" "$t/test_cjk_load.py" --port 8900 --static "$DIST" --work "$work") ;;
    r7)         CMD=("${PY_CMD[@]}" "$t/test_r7.py" --static "$DIST" --work "$work") ;;
    showreel)   CMD=("${PY_CMD[@]}" "$t/test_showreel.py" --static "$DIST" --work "$work") ;;
    nordic)     CMD=("${PY_CMD[@]}" "$t/test_nordic.py" --port 8895 --work "$OUT/nordic" --static "$DIST") ;;
    i18n)       CMD=("${PY_CMD[@]}" "$t/test_i18n.py" --static "$DIST" --work "$work") ;;
    reconnect)  CMD=("${PY_CMD[@]}" "$t/test_reconnect.py" --static "$DIST" --work "$work") ;;
    axe-matrix) CMD=("${PY_CMD[@]}" "$t/measure_ux.py" --matrix --static "$DIST" --out "$OUT/axe" --port 8810 --work "$work") ;;
    axe-preroll) CMD=("${PY_CMD[@]}" "$t/axe_preroll.py" --static "$DIST" --port 8940 --work "$work") ;;
    bundle)     CMD=("${PY_CMD[@]}" -c "$BUNDLE_PY" "$DIST") ;;
  esac
}

mem_gate() {  # returns 0 to run the step, 1 to skip it; sets MEM_NOTE on skip
  local waited=0 cur
  while :; do
    cur=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
    if (( cur <= MEM_MAX )); then return 0; fi
    if (( waited >= MEM_WAIT_MAX )); then
      MEM_NOTE="memory.current=$cur > MEM_MAX=$MEM_MAX for ${waited}s"
      return 1
    fi
    echo "[gate] memory.current=$cur above $MEM_MAX, waiting ${MEM_POLL}s" >&2
    sleep "$MEM_POLL"
    waited=$((waited + MEM_POLL))
  done
}

alive() {  # a zombie counts as finished (kill -0 succeeds on zombies)
  local st
  st=$(ps -o stat= -p "$1" 2>/dev/null | tr -d ' ')
  [[ -n $st && $st != Z* ]]
}

run_step() {  # $1 step, $2 limit in seconds; runs CMD; sets STEP_RC and STEP_TIMED_OUT
  local step=$1 limit=$2 pid pgid start
  STEP_TIMED_OUT=0
  setsid "${CMD[@]}" >"$OUT/$step.log" 2>&1 </dev/null &
  pid=$!
  pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
  [[ $pgid =~ ^[0-9]+$ ]] || pgid=$pid
  CUR_PGID=$pgid
  start=$(date +%s)
  while alive "$pid"; do
    if (( $(date +%s) - start >= limit )); then
      STEP_TIMED_OUT=1
      echo "[gate] ${limit}s timeout: SIGTERM to process group $pgid" >>"$OUT/$step.log"
      kill -TERM -- "-$pgid" 2>/dev/null
      sleep 5
      echo "[gate] SIGKILL to process group $pgid" >>"$OUT/$step.log"
      kill -KILL -- "-$pgid" 2>/dev/null
      break
    fi
    sleep 1
  done
  wait "$pid" 2>/dev/null
  STEP_RC=$?
  kill -KILL -- "-$pgid" 2>/dev/null   # whatever the step left behind (servers, replays, chromium)
  CUR_PGID=""
  if (( STEP_TIMED_OUT )); then STEP_RC=124; fi
}

last_line() {  # last SUMMARY or RESULT line of a log
  local line
  line=$(grep -E '^(SUMMARY|RESULT)' "$1" 2>/dev/null | tail -n 1)
  printf '%s' "${line:-NO-SUMMARY-LINE}"
}

RESULTS=()
ANY_FAIL=0
for step in "${STEPS[@]}"; do
  selected "$step" || continue
  limit_var="TIMEOUT_$(tr 'a-z-' 'A-Z_' <<<"$step")"
  limit=${!limit_var:-$DEFAULT_TIMEOUT}
  build_cmd "$step"
  if ! mem_gate; then
    log_line "$step" "-" "SKIP memory gate: $MEM_NOTE"
    RESULTS+=("$step|SKIP|-|0|memory gate: $MEM_NOTE")
    ANY_FAIL=1
    continue
  fi
  echo "== $(date '+%T') $step (limit ${limit}s)"
  t0=$(date +%s)
  run_step "$step" "$limit"
  rc=$STEP_RC
  if (( STEP_TIMED_OUT )); then
    line=TIMEOUT
  else
    line=$(last_line "$OUT/$step.log")
    if [[ $step == axe-matrix ]]; then
      line=$("${PY_CMD[@]}" -c "$AXE_PY" "$OUT/axe/summary.json" 2>&1)
      axe_rc=$?
      if (( rc == 0 && axe_rc != 0 )); then rc=$axe_rc; fi
    fi
  fi
  secs=$(( $(date +%s) - t0 ))
  if (( STEP_TIMED_OUT )); then status=TIMEOUT
  elif (( rc == 0 )); then status=PASS
  else status=FAIL; fi
  if (( STEP_TIMED_OUT || rc != 0 )); then ANY_FAIL=1; fi
  log_line "$step" "$rc" "$line"
  RESULTS+=("$step|$status|$rc|$secs|$line")
done

if (( ${#RESULTS[@]} == 0 )); then
  echo "run_gate.sh: no steps selected" >&2
  exit 2
fi

echo
printf '%-12s %-8s %5s %6s  %s\n' step status rc secs result
for r in "${RESULTS[@]}"; do
  IFS='|' read -r s st rc_ secs_ ln <<<"$r"
  printf '%-12s %-8s %5s %6s  %s\n' "$s" "$st" "$rc_" "$secs_" "$ln"
done
echo "gate log: $OUT/gate.log   step logs: $OUT/<step>.log"
(( ANY_FAIL == 0 ))
