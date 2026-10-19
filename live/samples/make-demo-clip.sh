#!/usr/bin/env bash
# Builds the bilingual two-speaker demo clip used to rehearse noScribe Live.
#
# Sources (public-domain LibriVox readings, hosted on archive.org):
#   EN  Abraham Lincoln, "Gettysburg Address"
#   ZH  Lu Xun, preface to "Call to Arms" (呐喊 自序), read in Mandarin
# Output: live/samples/demo-en-zh.mp3 (mono, 16 kHz, 64 kbit/s)
#
# Downloads are cached: each source is fetched once into its own directory (dl-en/, dl-zh/).
# The clip is rebuilt on every run, so edits to TURNS below take effect.
set -euo pipefail

# ---- turns: edit these ------------------------------------------------------
# Each turn is "<source> <start_s> <end_s>", played in order. EN = dl-en, ZH = dl-zh.
TURNS=(
  "EN 0 40"
  "ZH 20 60"
  "EN 40 80"
  "ZH 60 100"
  "EN 80 120"
)
GAP_S=0.6          # silence between consecutive turns, in seconds
OUT_RATE=16000     # Hz
OUT_BITRATE=64k
# -----------------------------------------------------------------------------

SAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EN_URL="https://archive.org/download/gettysburg_address_librivox/gettysburg_address_lincoln_64kb.mp3"
ZH_URL="https://archive.org/download/call_to_arms_jl_librivox/calltoarms_01_lu_64kb.mp3"
EN_DIR="$SAMPLES_DIR/dl-en"
ZH_DIR="$SAMPLES_DIR/dl-zh"
EN_FILE="$EN_DIR/gettysburg_address_lincoln_64kb.mp3"
ZH_FILE="$ZH_DIR/calltoarms_01_lu_64kb.mp3"
OUT="$SAMPLES_DIR/demo-en-zh.mp3"

for tool in curl ffmpeg ffprobe awk; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "make-demo-clip: $tool is required" >&2
    exit 1
  fi
done

# fetch URL DIR FILE: download once. The directory is emptied and recreated before the
# download, so it only ever contains that one file.
fetch() {
  local url="$1" dir="$2" file="$3"
  if [ -s "$file" ]; then
    echo "have $(basename "$file"), skipping download"
    return
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  echo "downloading $url"
  curl -fL --retry 3 --connect-timeout 20 -o "$file.part" "$url"
  mv "$file.part" "$file"
}

duration_of() {
  ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"
}

# "SS.ss" -> "M:SS.ss"
mmss() {
  awk -v s="$1" 'BEGIN { m = int(s / 60); printf "%d:%05.2f", m, s - 60 * m }'
}

fetch "$EN_URL" "$EN_DIR" "$EN_FILE"
fetch "$ZH_URL" "$ZH_DIR" "$ZH_FILE"

# Warn if a source is shorter than the turns that use it. The clip would come out short.
for spec in "${TURNS[@]}"; do
  read -r src start end <<<"$spec"
  case "$src" in
    EN) file="$EN_FILE" ;;
    ZH) file="$ZH_FILE" ;;
    *) echo "make-demo-clip: unknown source in TURNS: $src" >&2; exit 1 ;;
  esac
  have="$(duration_of "$file")"
  if awk -v d="$have" -v e="$end" 'BEGIN { exit !(d + 0 < e + 0) }'; then
    echo "warning: $src recording is ${have}s long but a turn ends at ${end}s" >&2
  fi
done

# Build one filter graph: each turn is trimmed and resampled to mono 16 kHz, and a
# silent gap follows every turn except the last. concat joins them all.
inputs=(-i "$EN_FILE" -i "$ZH_FILE")
graph=""
labels=""
count=${#TURNS[@]}
i=0
for spec in "${TURNS[@]}"; do
  read -r src start end <<<"$spec"
  if [ "$src" = "EN" ]; then idx=0; else idx=1; fi
  graph+="[$idx:a]atrim=start=$start:end=$end,asetpts=PTS-STARTPTS,aresample=$OUT_RATE,aformat=sample_fmts=s16:channel_layouts=mono[t$i];"
  labels+="[t$i]"
  if [ "$i" -lt $((count - 1)) ]; then
    graph+="anullsrc=channel_layout=mono:sample_rate=$OUT_RATE,atrim=duration=$GAP_S,aformat=sample_fmts=s16:channel_layouts=mono[g$i];"
    labels+="[g$i]"
  fi
  i=$((i + 1))
done
graph+="${labels}concat=n=$((2 * count - 1)):v=0:a=1[out]"

echo "building $OUT"
ffmpeg -nostdin -v error -y "${inputs[@]}" -filter_complex "$graph" -map "[out]" \
  -ac 1 -ar "$OUT_RATE" -codec:a libmp3lame -b:a "$OUT_BITRATE" "$OUT.tmp.mp3"
mv "$OUT.tmp.mp3" "$OUT"

actual="$(duration_of "$OUT")"
expected="$(printf '%s\n' "${TURNS[@]}" | awk -v g="$GAP_S" '{ total += $3 - $2; n++ } END { printf "%.2f", total + (n - 1) * g }')"
echo "demo clip: $OUT"
echo "duration:  $(mmss "$actual") (${actual}s; the turn list predicts ${expected}s)"
