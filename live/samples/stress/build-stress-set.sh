#!/usr/bin/env bash
# Builds the stress test-audio set in live/samples/stress/ for exercising noScribe Live with
# awkward inputs: Mandarin, Mandarin/English code-switching, several speakers, background
# noise, very long and silent recordings, a very short clip, several container/codec formats,
# and unreadable files.
#
# Sources and licences are listed in SOURCES.md next to this script. Every real recording is a
# LibriVox reading (public domain / CC0) hosted on archive.org. Downloads are untrusted data:
# they are only ever decoded by ffmpeg/ffprobe and never executed.
#
# Usage: live/samples/stress/build-stress-set.sh
# Idempotent: existing downloads and outputs are kept. Delete a file to rebuild it.
set -euo pipefail

STRESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLES_DIR="$(cd "$STRESS_DIR/.." && pwd)"
DL="$STRESS_DIR/dl"        # downloads (git-ignored), one subdirectory per source
WORK="$DL/work"            # intermediate excerpts (git-ignored)
RATE=16000                 # sample rate of the mono speech clips

for tool in curl ffmpeg ffprobe awk; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "build-stress-set: $tool is required" >&2
    exit 1
  fi
done

# ---- sources -----------------------------------------------------------------
# EN: Abraham Lincoln, "The Gettysburg Address" (LibriVox)
# ZH: Lu Xun, "Call to Arms" preface, Mandarin reading (LibriVox). Accent NOT verified as Taiwanese.
# THIRD: Abner Doubleday, "Chancellorsville and Gettysburg", part 00 (LibriVox, a different reader).
EN_URL="https://archive.org/download/gettysburg_address_librivox/gettysburg_address_lincoln_64kb.mp3"
ZH_URL="https://archive.org/download/call_to_arms_jl_librivox/calltoarms_01_lu_64kb.mp3"
THIRD_URL="https://archive.org/download/chancellorsville_gettysburg_ms_librivox/chancellorsvillegettysburg_00_doubleday_64kb.mp3"

# fetch URL DIR FILE: download URL to FILE once. DIR is emptied first, so it only ever holds this file.
fetch() {
  local url="$1" dir="$2" file="$3"
  if [ -s "$file" ]; then
    echo "have $(basename "$file"), skipping download"
    return 0
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  echo "downloading $url"
  curl -fL --max-time 120 --retry 3 --connect-timeout 20 -o "$file.part" "$url"
  mv "$file.part" "$file"
}

# Reuse the copies that make-demo-clip.sh already fetched; otherwise fetch into dl/.
EN_FILE="$SAMPLES_DIR/dl-en/gettysburg_address_lincoln_64kb.mp3"
ZH_FILE="$SAMPLES_DIR/dl-zh/calltoarms_01_lu_64kb.mp3"
THIRD_FILE="$DL/librivox-third/chancellorsvillegettysburg_00_doubleday_64kb.mp3"
if [ ! -s "$EN_FILE" ]; then
  EN_FILE="$DL/librivox-en/gettysburg_address_lincoln_64kb.mp3"
  fetch "$EN_URL" "$DL/librivox-en" "$EN_FILE"
fi
if [ ! -s "$ZH_FILE" ]; then
  ZH_FILE="$DL/librivox-zh/calltoarms_01_lu_64kb.mp3"
  fetch "$ZH_URL" "$DL/librivox-zh" "$ZH_FILE"
fi
fetch "$THIRD_URL" "$DL/librivox-third" "$THIRD_FILE"
mkdir -p "$WORK"

# ---- helpers -----------------------------------------------------------------

# emit TARGET ARGS...: run ffmpeg with ARGS, writing TARGET through a temp file. The temp name
# keeps TARGET's extension, so ffmpeg still picks the muxer from it. Skips when TARGET exists.
emit() {
  local target="$1"
  shift
  local name tmp
  name="$(basename "$target")"
  if [ -s "$target" ]; then
    echo "have $name, skipping build"
    return 0
  fi
  tmp="$(dirname "$target")/.part-$name"
  echo "building $name"
  ffmpeg -nostdin -hide_banner -v error -y "$@" "$tmp"
  mv "$tmp" "$target"
}

# splice TARGET GAP_S FILE START DUR [FILE START DUR ...]: cut each segment (input seek),
# resample it to mono RATE, and join the segments with GAP_S seconds of silence between them.
splice() {
  local target="$1" gap="$2"
  shift 2
  local -a args=()
  local graph="" parts="" n=0 idx=0
  while [ "$#" -ge 3 ]; do
    args+=(-ss "$2" -t "$3" -i "$1")
    graph+="[$idx:a]asetpts=PTS-STARTPTS,aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[t$idx];"
    parts+="[t$idx]"
    n=$((n + 1))
    if [ "$#" -gt 3 ] && [ "$gap" != "0" ]; then
      graph+="anullsrc=channel_layout=mono:sample_rate=$RATE,atrim=duration=$gap,aformat=sample_fmts=s16:channel_layouts=mono[g$idx];"
      parts+="[g$idx]"
      n=$((n + 1))
    fi
    idx=$((idx + 1))
    shift 3
  done
  graph+="${parts}concat=n=$n:v=0:a=1[out]"
  emit "$target" "${args[@]}" -filter_complex "$graph" -map "[out]" -ac 1 -ar "$RATE" -codec:a libmp3lame -b:a 64k
}

# mean_db FILE: mean loudness of FILE in dB (ffmpeg volumedetect).
mean_db() {
  local v
  v="$(ffmpeg -nostdin -hide_banner -i "$1" -af volumedetect -vn -f null - 2>&1 \
    | sed -n 's/.*mean_volume: \(-\{0,1\}[0-9.]*\) dB.*/\1/p' | tail -n 1)"
  if [ -z "$v" ]; then
    echo "build-stress-set: could not measure loudness of $1" >&2
    exit 1
  fi
  echo "$v"
}

# ---- 01: the demo clip, copied unchanged ---------------------------------------
if [ ! -e "$STRESS_DIR/01-demo-en-zh.mp3" ]; then
  if [ ! -s "$SAMPLES_DIR/demo-en-zh.mp3" ]; then
    "$SAMPLES_DIR/make-demo-clip.sh"
  fi
  cp "$SAMPLES_DIR/demo-en-zh.mp3" "$STRESS_DIR/.part-01-demo-en-zh.mp3"
  mv "$STRESS_DIR/.part-01-demo-en-zh.mp3" "$STRESS_DIR/01-demo-en-zh.mp3"
  echo "built 01-demo-en-zh.mp3"
else
  echo "have 01-demo-en-zh.mp3, skipping build"
fi

# ---- shared 60 s Mandarin/English excerpt (30 s English + 30 s Mandarin) ------------
EXCERPT="$WORK/excerpt-60s.wav"
emit "$EXCERPT" -ss 0 -t 30 -i "$EN_FILE" -ss 20 -t 30 -i "$ZH_FILE" \
  -filter_complex "[0:a]aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[a];[1:a]aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[b];[a][b]concat=n=2:v=0:a=1[out]" \
  -map "[out]" -codec:a pcm_s16le

# ---- 02: Mandarin speech, 2 min (LibriVox reader; accent not verified as Taiwanese) ----
emit "$STRESS_DIR/02-zh-tw-speech.mp3" -ss 30 -t 120 -i "$ZH_FILE" -ac 1 -ar "$RATE" -codec:a libmp3lame -b:a 64k

# ---- 03: three speakers in turn-taking (SYNTHETIC) ---------------------------------
# Six 12 s turns per reader, rotating EN, ZH, THIRD, with 0.4 s between turns (about 3.7 min).
segs=()
for j in 0 1 2 3 4 5; do
  for f in "$EN_FILE" "$ZH_FILE" "$THIRD_FILE"; do
    segs+=("$f" "$((j * 12))" 12)
  done
done
splice "$STRESS_DIR/03-multi-speaker.mp3" 0.4 "${segs[@]}"

# ---- 04: Mandarin/English code-switching (SYNTHETIC) -------------------------------
# Twenty fixed 5 s cuts (no low-energy search), alternating English and Mandarin, no gaps.
segs=()
for k in 0 1 2 3 4 5 6 7 8 9; do
  segs+=("$EN_FILE" "$((k * 5))" 5 "$ZH_FILE" "$((60 + k * 5))" 5)
done
splice "$STRESS_DIR/04-codeswitch-zh-en.mp3" 0 "${segs[@]}"

# ---- 05: speech over background noise, about 5 dB SNR (SYNTHETIC) ---------------------
# Speech: Mandarin, 120 s. Noise layer: pink noise plus an English babble layer (120 s).
# The noise layer is scaled so that mean(speech) - mean(noise) = 5 dB.
SPEECH="$WORK/speech-05.wav"
emit "$SPEECH" -ss 150 -t 120 -i "$ZH_FILE" -ac 1 -ar "$RATE" -codec:a pcm_s16le
NOISE="$WORK/noise-05.wav"
emit "$NOISE" -f lavfi -i "anoisesrc=color=pink:amplitude=0.5:duration=120:sample_rate=$RATE" \
  -ss 0 -t 120 -i "$EN_FILE" \
  -filter_complex "[0:a]aformat=sample_fmts=s16:channel_layouts=mono[p];[1:a]aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[b];[p][b]amix=inputs=2:duration=first:dropout_transition=0[out]" \
  -map "[out]" -ac 1 -ar "$RATE" -codec:a pcm_s16le
speech_db="$(mean_db "$SPEECH")"
noise_db="$(mean_db "$NOISE")"
gain="$(awk -v s="$speech_db" -v n="$noise_db" 'BEGIN { printf "%.2f", s - 5 - n }')"
emit "$STRESS_DIR/05-noisy-music.mp3" -i "$SPEECH" -i "$NOISE" \
  -filter_complex "[1:a]volume=${gain}dB[n];[0:a][n]amix=inputs=2:duration=first:dropout_transition=0[out]" \
  -map "[out]" -ac 1 -ar "$RATE" -codec:a libmp3lame -b:a 64k

# ---- 06: long recording, about 11.6 min (the full Mandarin LibriVox chapter) -------------
emit "$STRESS_DIR/06-long.mp3" -i "$ZH_FILE" -ac 1 -ar "$RATE" -codec:a libmp3lame -b:a 64k

# ---- 07: 25 s speech, 90 s digital silence, 25 s speech ----------------------------
emit "$STRESS_DIR/07-long-silence.mp3" \
  -ss 0 -t 25 -i "$EN_FILE" \
  -f lavfi -t 90 -i "anullsrc=channel_layout=mono:sample_rate=$RATE" \
  -ss 60 -t 25 -i "$ZH_FILE" \
  -filter_complex "[0:a]aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[a];[1:a]aformat=sample_fmts=s16:channel_layouts=mono[s];[2:a]aresample=$RATE,aformat=sample_fmts=s16:channel_layouts=mono[b];[a][s][b]concat=n=3:v=0:a=1[out]" \
  -map "[out]" -ac 1 -ar "$RATE" -codec:a libmp3lame -b:a 64k

# ---- 08: very short clip, 3 s of speech, 16 kHz mono WAV ---------------------------
emit "$STRESS_DIR/08-very-short.wav" -ss 5 -t 3 -i "$EN_FILE" -ac 1 -ar "$RATE" -codec:a pcm_s16le

# ---- 09-13: format variety, all from the 60 s excerpt -------------------------------
emit "$STRESS_DIR/09-format.m4a" -i "$EXCERPT" -codec:a aac -b:a 96k
emit "$STRESS_DIR/10-format.wav" -i "$EXCERPT" -ac 2 -ar 44100 -codec:a pcm_s16le
emit "$STRESS_DIR/11-format-video.mp4" -f lavfi -i "testsrc2=size=640x360:rate=15" -i "$EXCERPT" \
  -map 0:v -map 1:a -shortest -t 60 -c:v libx264 -preset veryfast -pix_fmt yuv420p -codec:a aac -b:a 96k
emit "$STRESS_DIR/12-format.ogg" -i "$EXCERPT" -codec:a libopus -b:a 64k
emit "$STRESS_DIR/13-format.webm" -f lavfi -i "testsrc2=size=640x360:rate=15" -i "$EXCERPT" \
  -map 0:v -map 1:a -shortest -t 60 -c:v libvpx -b:v 400k -deadline realtime -cpu-used 8 -codec:a libopus -b:a 64k

# ---- 90-92: unreadable inputs -----------------------------------------------------
if [ ! -e "$STRESS_DIR/90-corrupt.mp3" ]; then
  head -c 2000000 /dev/urandom > "$STRESS_DIR/.part-90-corrupt.mp3"
  mv "$STRESS_DIR/.part-90-corrupt.mp3" "$STRESS_DIR/90-corrupt.mp3"
  echo "built 90-corrupt.mp3"
fi
if [ ! -e "$STRESS_DIR/91-truncated.m4a" ]; then
  head -c 20480 "$STRESS_DIR/09-format.m4a" > "$STRESS_DIR/.part-91-truncated.m4a"
  mv "$STRESS_DIR/.part-91-truncated.m4a" "$STRESS_DIR/91-truncated.m4a"
  echo "built 91-truncated.m4a"
fi
if [ ! -e "$STRESS_DIR/92-empty.wav" ]; then
  : > "$STRESS_DIR/.part-92-empty.wav"
  mv "$STRESS_DIR/.part-92-empty.wav" "$STRESS_DIR/92-empty.wav"
  echo "built 92-empty.wav"
fi

# ---- table ------------------------------------------------------------------------
echo
echo "| file | duration (s, ffprobe format=duration) | codec(s) | bytes |"
echo "|---|---|---|---|"
for f in "$STRESS_DIR"/[0-9][0-9]-*; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | head -n 1 || true)"
  if [[ "$dur" =~ ^[0-9.]+$ ]]; then
    dur="$(printf '%.2f' "$dur")"
  else
    dur="n/a"
  fi
  codecs="$(ffprobe -v error -show_entries stream=codec_name -of csv=p=0 "$f" 2>/dev/null | paste -sd+ - || true)"
  printf '| %s | %s | %s | %s |\n' "$name" "$dur" "${codecs:-n/a}" "$(stat -c %s "$f")"
done
