/**
 * Pure helpers for the character reveal: grapheme splitting and the reveal speed. No React, no DOM.
 */

/** Slowest reveal, in graphemes per second. */
export const BASE_RATE = 50;
/** Fastest reveal, in graphemes per second. */
export const MAX_RATE = 2000;
/** The reveal should have shown the queue's backlog within this many seconds of the oldest segment's arrival. */
export const HORIZON_S = 1.0;
/** Floor on the time left to the horizon (s). Caps the speed when the oldest segment is near its deadline. */
export const MIN_LEFT_S = 0.15;
/** Hard cap (ms): a segment still unrevealed this long after it arrived is shown in full at once. */
export const HARD_CAP_MS = 1200;

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

/**
 * Graphemes per second for a queue holding `backlog` graphemes whose oldest segment is `ageS` seconds old. The rate
 * is the backlog over the time left to the horizon, so the queue drains by HORIZON_S after that arrival. Never below
 * BASE_RATE (a short segment still types at a readable pace), never above MAX_RATE. Recomputed every frame: as the
 * backlog falls the time left falls with it, so the drain is linear and empties at the horizon, not exponentially.
 */
export function revealRate(backlog: number, ageS: number): number {
  const left = Math.max(MIN_LEFT_S, HORIZON_S - Math.max(0, ageS));
  return Math.min(MAX_RATE, Math.max(BASE_RATE, backlog / left));
}
