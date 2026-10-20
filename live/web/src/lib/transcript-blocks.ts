import type { Segment } from "@/lib/live-state";
import { isOverlapLabel, speakerKey } from "@/lib/speakers";
import { isCjkChar, needsSpaceBetween } from "@/lib/format";

/** A paragraph starts at a pause of this many seconds between segments. */
const PAUSE_BREAK_S = 1.5;
/** Past this many seconds, a paragraph breaks at the next sentence end (or the next segment boundary after the hard limit). */
const PARAGRAPH_SOFT_S = 30;
/** Past this many seconds, a paragraph breaks at the next segment boundary, sentence end or not. */
const PARAGRAPH_HARD_S = 45;

export interface SegmentItem {
  seg: Segment;
  /** "//" overlap segment: rendered inline inside the current paragraph with a tag. */
  overlap: boolean;
  /** A space is needed before this item (English-like neighbours inside a paragraph). */
  spaceBefore: boolean;
  /** A thin separator is needed before this item (CJK neighbours; Whisper gives no spaces between them). */
  thinBefore: boolean;
}

export interface Paragraph {
  /** Index of the paragraph's first segment; stable across renders. */
  id: number;
  /** Start of the paragraph's first segment, seconds. */
  start: number;
  items: SegmentItem[];
}

export interface SpeakerBlock {
  /** Index of the block's first segment; stable across renders. */
  id: number;
  /** Speaker label without the "//" prefix; "" when the segment had no speaker. */
  speaker: string;
  start: number;
  paragraphs: Paragraph[];
}

/** Ends with a sentence terminator (Chinese or Western), ignoring closing quotes and brackets. */
function endsSentence(text: string): boolean {
  return /[。！？!?…][\s"'”’」』）)]*$/.test(text.trimEnd());
}

/** True when the segment belongs in a new paragraph rather than the paragraph so far. */
function startsParagraph(paragraph: Paragraph, prev: Segment, seg: Segment): boolean {
  const length = prev.end - paragraph.start;
  if (seg.start - prev.end >= PAUSE_BREAK_S) return true;
  if (length >= PARAGRAPH_HARD_S) return true;
  return length >= PARAGRAPH_SOFT_S && endsSentence(prev.text);
}

/** Two CJK characters meet at the boundary between two segments. */
function cjkMeets(prevText: string, nextText: string): boolean {
  return isCjkChar(prevText.trimEnd().slice(-1)) && isCjkChar(nextText.trimStart().charAt(0));
}

/**
 * Groups consecutive segments of the same speaker into blocks, and each block into paragraphs.
 * Paragraphs only break on segment boundaries, so a segment is never split and a Chinese sentence
 * (which Whisper writes as one or more whole segments) is never cut in the middle.
 */
export function buildBlocks(segments: readonly Segment[]): SpeakerBlock[] {
  const blocks: SpeakerBlock[] = [];
  let prev: Segment | null = null;
  for (const seg of segments) {
    const before: Segment | null = prev;
    const overlap = isOverlapLabel(seg.speaker);
    const speaker = speakerKey(seg.speaker);
    let block: SpeakerBlock | undefined = blocks[blocks.length - 1];
    if (!block || (!overlap && block.speaker !== speaker)) {
      block = { id: seg.index, speaker, start: seg.start, paragraphs: [] };
      blocks.push(block);
    }
    let paragraph: Paragraph | undefined = block.paragraphs[block.paragraphs.length - 1];
    const joins = paragraph !== undefined && before !== null && (overlap || !startsParagraph(paragraph, before, seg));
    if (!paragraph || !joins) {
      paragraph = { id: seg.index, start: seg.start, items: [] };
      block.paragraphs.push(paragraph);
    }
    paragraph.items.push({
      seg,
      overlap,
      spaceBefore: before !== null && joins && needsSpaceBetween(before.text, seg.text),
      thinBefore: before !== null && joins && cjkMeets(before.text, seg.text),
    });
    prev = seg;
  }
  return blocks;
}
