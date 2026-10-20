// How a run ended, in the words the page uses for it, and a readable form of raw CLI errors.
// Pure: no React, no DOM, no clock. The raw error text is kept verbatim for a disclosure; the
// humanised form is only ever shown as a headline or sub-line.

import type { RunState } from "@/lib/live-state";

export type EndKind =
  /** The CLI died without writing run_end. */
  | "stale"
  /** The audio could not be decoded: unsupported format or damaged file. */
  | "unreadable-audio"
  /** Any other error. */
  | "failed"
  | "canceled"
  /** Finished, but no segment was produced. */
  | "no-speech"
  /** Finished with at least one segment. */
  | "finished";

export interface EndDescription {
  kind: EndKind;
  /** Headline: what happened. */
  title: string;
  /** Muted sub-line: why, or the humanised error for a failed run. Null when there is nothing to add. */
  detail: string | null;
  /** The CLI's error text, trimmed, for a disclosure. Null when the run gave none. */
  rawError: string | null;
}

/** The fields `describeEnd` reads. A whole RunState satisfies it. */
export type EndInput = Pick<RunState, "endStatus" | "stale" | "error" | "segments">;

export const UNREADABLE_AUDIO_TITLE = "無法讀取音訊檔（格式不支援或檔案損毀）";
const STALE_DETAIL = "noScribe 在完成前停止了（行程已結束）。";
const MAX_HUMAN_CHARS = 120;

/** Lower-case substrings that mean the audio could not be read. */
const UNREADABLE_MARKERS = [
  "errno 1094995529",
  "invalid data found when processing input",
  "moov atom not found",
  "does not contain any stream",
];

/** An absolute POSIX or Windows path at a word boundary, matched whole. */
const ABSOLUTE_PATH = /(?<![^\s'"`(=:])(?:[A-Za-z]:)?[\\/](?:[^\s\\/'"`()<>]+[\\/])*[^\s\\/'"`()<>]+/g;

/** Replaces every absolute path with its last component, so no directory prefix is shown. */
function stripPaths(text: string): string {
  return text.replace(ABSOLUTE_PATH, (match) => match.split(/[\\/]/).pop() || match);
}

/** Cuts text to `max` code points, with an ellipsis when it was cut. */
function clip(text: string, max: number): string {
  const chars = [...text];
  return chars.length > max ? `${chars.slice(0, max - 1).join("")}…` : text;
}

/** True when lower-cased error text says the audio could not be read. */
function isUnreadableAudio(lower: string): boolean {
  if (UNREADABLE_MARKERS.some((marker) => lower.includes(marker))) return true;
  return lower.includes("converting the audio") && lower.includes("tuple index out of range");
}

/**
 * One readable line for a raw CLI error: a known cause in Chinese, otherwise the first line with its
 * paths reduced to file names, trimmed to about 120 characters. Null when there is no error text.
 */
export function humanizeError(raw: string | null | undefined): string | null {
  const text = raw?.trim();
  if (!text) return null;
  const lower = text.toLowerCase();
  if (isUnreadableAudio(lower)) return UNREADABLE_AUDIO_TITLE;
  if (lower.includes("cuda out of memory")) return "GPU 記憶體不足";
  if (lower.includes("no such file or directory")) return "找不到音訊檔";
  const firstLine = text.split(/\r?\n/, 1)[0].trim();
  return clip(stripPaths(firstLine), MAX_HUMAN_CHARS);
}

/**
 * What the page says about a run that has ended or gone stale. Returns null while the run is still
 * active. Precedence matches `displayPhase`: a recorded end status wins over the stale flag.
 */
export function describeEnd(run: EndInput): EndDescription | null {
  const rawError = run.error?.trim() || null;

  if (run.endStatus === "finished") {
    return run.segments.length === 0
      ? { kind: "no-speech", title: "沒有偵測到語音", detail: null, rawError }
      : { kind: "finished", title: "轉錄完成", detail: null, rawError };
  }
  if (run.endStatus === "canceled") {
    return { kind: "canceled", title: "已取消", detail: null, rawError };
  }
  if (run.endStatus === "error") {
    if (rawError && isUnreadableAudio(rawError.toLowerCase())) {
      return { kind: "unreadable-audio", title: UNREADABLE_AUDIO_TITLE, detail: null, rawError };
    }
    return { kind: "failed", title: "轉錄失敗", detail: humanizeError(rawError), rawError };
  }
  if (run.stale) {
    return { kind: "stale", title: "轉錄意外中止", detail: STALE_DETAIL, rawError };
  }
  return null;
}
