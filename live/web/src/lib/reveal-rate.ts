/**
 * Pure helpers for the character reveal: grapheme splitting, the speed modes and their pacing constants. No React, no
 * DOM. The queue that applies them is in reveal-engine.ts.
 */

/** Speed modes. "continuous" follows the arrival rate of the feed; the others reveal at one fixed rate. */
export type RevealMode = "continuous" | "reading" | "normal" | "fast" | "custom";

export const REVEAL_MODES: readonly RevealMode[] = ["continuous", "reading", "normal", "fast", "custom"];

/** Fixed rates (graphemes per second) of the preset modes. */
export const PRESET_CPS = { reading: 12, normal: 30, fast: 70 } as const;

/** Range of the custom slider (graphemes per second). */
export const CUSTOM_MIN_CPS = 8;
export const CUSTOM_MAX_CPS = 120;
export const DEFAULT_CUSTOM_CPS = 30;

/** Rounds a custom rate into the slider range. A value that is not a number gives the default. */
export function clampCustomCps(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_CUSTOM_CPS;
  return Math.round(Math.min(CUSTOM_MAX_CPS, Math.max(CUSTOM_MIN_CPS, value)));
}

/**
 * The fixed rate (graphemes per second) for a mode. Continuous has no fixed rate: it returns the normal preset, which
 * the engine ignores in that mode.
 */
export function fixedRateFor(mode: RevealMode, customCps: number): number {
  if (mode === "reading" || mode === "normal" || mode === "fast") return PRESET_CPS[mode];
  if (mode === "custom") return clampCustomCps(customCps);
  return PRESET_CPS.normal;
}

/**
 * Continuous flow. The base rate is the arrival average times K, so the queue does not empty while the run is live.
 * The rate rises when the backlog would take longer than TARGET_S to show. It moves at most SLEW_PER_S per second.
 * After run_end the target is the backlog over TAIL_S, with the faster TAIL_SLEW_PER_S.
 */
export const FLOW = {
  /** Weight of each new arrival sample in the arrival average (exponential moving average). */
  ALPHA: 0.2,
  /** The reveal runs at this fraction of the arrival average. */
  K: 0.9,
  /** A backlog longer than this many seconds at the current rate raises the rate. */
  TARGET_S: 8,
  /** The tail after run_end finishes within this many seconds. */
  TAIL_S: 10,
  /** Largest relative change of the rate per second (20%). */
  SLEW_PER_S: 0.2,
  /** Largest relative change of the rate per second in the tail. */
  TAIL_SLEW_PER_S: 1,
  /** Lowest continuous rate. Text keeps moving while anything is queued. */
  MIN_CPS: 6,
  /** Highest continuous rate while the run is live. */
  MAX_CPS: 120,
  /** Highest rate in the tail. */
  TAIL_MAX_CPS: 400,
  /** Arrival average assumed until two arrivals of a run have been measured. */
  DEFAULT_CPS: 30,
  /** A backlog at or below this many graphemes counts as dry: the target drops to DRY_FACTOR of the base. */
  DRY_GRAPHEMES: 3,
  DRY_FACTOR: 0.6,
  /** Arrival gaps are clamped to [MIN_GAP_S, MAX_GAP_S] before a sample is taken. */
  MIN_GAP_S: 0.5,
  MAX_GAP_S: 30,
  /** Safety only: a backlog that would take longer than this many seconds at the current rate is shown at once. */
  SAFETY_FLUSH_S: 60,
} as const;

/** Fixed modes: a backlog that would take longer than this many seconds at the chosen rate shows the "behind" hint. */
export const BEHIND_S = 20;

/** A frame gap longer than this (ms), such as a hidden tab, shows the queue at once so the text is current on return. */
export const STALL_FLUSH_MS = 5000;

/** Longest frame step (ms) the reveal integrates in one go. Longer stalls are still bounded. */
export const MAX_FRAME_MS = 250;

const segmenter: Intl.Segmenter | null =
  typeof Intl !== "undefined" && typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

// One-entry memo: the same text is asked for several times in a row (count on arrival, slice on each frame).
let memoText: string | null = null;
let memoOffsets: number[] = [0];

/** UTF-16 offsets where each grapheme starts, then text.length. The array's length minus one is the grapheme count. */
export function graphemeOffsets(text: string): number[] {
  if (text === memoText) return memoOffsets;
  const offsets: number[] = [];
  if (segmenter) {
    for (const part of segmenter.segment(text)) offsets.push(part.index);
  } else {
    let at = 0;
    for (const char of Array.from(text)) {
      offsets.push(at);
      at += char.length;
    }
  }
  offsets.push(text.length);
  memoText = text;
  memoOffsets = offsets;
  return offsets;
}

/** Number of user-perceived characters (graphemes) in text. */
export function graphemeCount(text: string): number {
  return graphemeOffsets(text).length - 1;
}

/** The leading `count` graphemes of text, as a string. Counts past the end give the whole text. */
export function sliceGraphemes(text: string, count: number): string {
  return splitGraphemes(text, count)[0];
}

/**
 * Splits text at a grapheme boundary: the leading `count` graphemes, and the rest. Counts past the end give the whole
 * text and an empty rest; the two parts always join back to text.
 */
export function splitGraphemes(text: string, count: number): [string, string] {
  const offsets = graphemeOffsets(text);
  const n = Math.max(0, Math.min(count, offsets.length - 1));
  const at = offsets[n];
  return [text.slice(0, at), text.slice(at)];
}
