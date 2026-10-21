/**
 * Pure helpers for the character reveal: grapheme splitting and the reveal speed. No React, no DOM.
 */

/** Slowest reveal, in graphemes per second. */
export const BASE_RATE = 50;
/** Fastest reveal, in graphemes per second. */
export const MAX_RATE = 2000;
/** The reveal should have shown everything it holds within this many seconds. */
export const HORIZON_S = 1.2;

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
  const offsets = graphemeOffsets(text);
  const n = Math.max(0, Math.min(count, offsets.length - 1));
  return text.slice(0, offsets[n]);
}

/**
 * Graphemes per second needed to show `backlog` graphemes within HORIZON_S. Never below BASE_RATE, so a short
 * segment still types out at a readable pace; never above MAX_RATE.
 */
export function requiredRate(backlog: number): number {
  return Math.min(MAX_RATE, Math.max(BASE_RATE, backlog / HORIZON_S));
}
