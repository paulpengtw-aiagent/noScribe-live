import type { Segment } from "@/lib/live-state";
import { isOverlapLabel, speakerKey } from "@/lib/speakers";
import { needsSpaceBetween } from "@/lib/format";

export interface SegmentItem {
  seg: Segment;
  /** "//" overlap segment: rendered inline inside the current block with a tag. */
  overlap: boolean;
  /** A space is needed before this item (English-like neighbours inside a block). */
  spaceBefore: boolean;
}

export interface SpeakerBlock {
  /** Index of the block's first segment; stable across renders. */
  id: number;
  /** Speaker label without the "//" prefix; "" when the segment had no speaker. */
  speaker: string;
  start: number;
  items: SegmentItem[];
}

/** Groups consecutive segments of the same speaker into blocks. */
export function buildBlocks(segments: readonly Segment[]): SpeakerBlock[] {
  const blocks: SpeakerBlock[] = [];
  let prev: Segment | null = null;
  for (const seg of segments) {
    const overlap = isOverlapLabel(seg.speaker);
    const speaker = speakerKey(seg.speaker);
    const current: SpeakerBlock | undefined = blocks[blocks.length - 1];
    if (!current || (!overlap && current.speaker !== speaker)) {
      blocks.push({ id: seg.index, speaker, start: seg.start, items: [{ seg, overlap, spaceBefore: false }] });
    } else {
      const spaceBefore = prev ? needsSpaceBetween(prev.text, seg.text) : false;
      current.items.push({ seg, overlap, spaceBefore });
    }
    prev = seg;
  }
  return blocks;
}
