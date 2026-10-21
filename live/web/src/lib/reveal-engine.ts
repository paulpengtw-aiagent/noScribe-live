/**
 * The reveal queue for one run: live segments type out one grapheme at a time, strictly in arrival order.
 *
 * Pure and clock-free: the caller passes the frame step (ms) to advance(), and the arrival time (ms) each segment
 * carries. No React, no DOM, so it can be unit-tested with plain Node. See reveal-rate.ts for the speed rule.
 */

import { graphemeCount, requiredRate } from "./reveal-rate.ts";

/** The segment fields the engine reads. Structural, so the engine does not depend on the live-state types. */
export interface RevealSegment {
  /** Position in the run; stable and unique within it. */
  index: number;
  text: string;
  /** True only when the segment arrived through a live feed event, not a snapshot. */
  live: boolean;
  /** Arrival time, ms (Date.now() when the page processed the segment). */
  recvAt: number;
}

/** What the transcript draws from the queue. */
export interface RevealView {
  /** Index of the segment revealing now, or null when nothing is queued. */
  head: number | null;
  /** Graphemes of the head already shown (of the trimmed segment text). */
  shown: number;
  /** Indexes queued behind the head: their text is not drawn yet. */
  waiting: ReadonlySet<number>;
}

interface Item {
  index: number;
  total: number;
  arrivedAt: number;
}

export class RevealEngine {
  /** The run the queue belongs to. undefined until the first reset. */
  runId: string | null | undefined = undefined;
  /** Segments fully revealed in the current run (flushed segments count as revealed). */
  revealedSegments = 0;

  // Segment indexes already queued or shown. A segment is queued at most once per run, so a re-sent snapshot never replays.
  private seen = new Set<number>();
  private queue: Item[] = [];
  /** Graphemes of queue[0] already shown. */
  private shown = 0;
  /** Fractional graphemes carried from one frame to the next, so the speed is steady at any frame rate. */
  private carry = 0;
  /** Graphemes per second for the whole queue. Set when segments are queued (requiredRate of the full backlog), then
   *  held while it drains. Recomputing it from the shrinking backlog every frame decays the drain exponentially, so a
   *  400-grapheme segment took 3.5 s instead of HORIZON_S. */
  private rate = 0;
  private cached: RevealView | null = null;

  /** Starts a run. Its current segments count as already shown, so nothing in them is queued. */
  reset(runId: string | null, segments: readonly RevealSegment[]): void {
    this.runId = runId;
    this.revealedSegments = 0;
    this.seen = new Set(segments.map((segment) => segment.index));
    this.queue = [];
    this.shown = 0;
    this.carry = 0;
    this.cached = null;
  }

  /** Queues the live segments not seen before, in the order given. Segments that are not live are marked seen and never queued. */
  sync(segments: readonly RevealSegment[]): void {
    let queued = false;
    for (const segment of segments) {
      if (this.seen.has(segment.index)) continue;
      this.seen.add(segment.index);
      if (!segment.live) continue;
      const total = graphemeCount(segment.text.trim());
      if (total === 0) continue;
      this.queue.push({ index: segment.index, total, arrivedAt: segment.recvAt });
      queued = true;
      this.cached = null;
    }
    if (queued) this.rate = requiredRate(this.backlog());
  }

  /** Graphemes still to show across the whole queue: the head's shown part is not counted. */
  private backlog(): number {
    let total = -this.shown;
    for (const item of this.queue) total += item.total;
    return total;
  }

  /** Shows everything queued at once. */
  flush(): void {
    if (this.queue.length === 0) return;
    this.revealedSegments += this.queue.length;
    this.queue = [];
    this.shown = 0;
    this.carry = 0;
    this.cached = null;
  }

  /** True while any text is still revealing. */
  busy(): boolean {
    return this.queue.length > 0;
  }

  /** Segments not yet fully revealed, the one revealing now included. */
  queued(): number {
    return this.queue.length;
  }

  /** How far the reveal trails the data: now minus the arrival of the oldest segment not yet fully shown. 0 when caught up. */
  lagMs(now: number): number {
    return this.queue.length === 0 ? 0 : Math.max(0, now - this.queue[0].arrivedAt);
  }

  /** Moves the reveal forward by `dtMs` of wall-clock time, at the rate needed to keep up with the backlog. */
  advance(dtMs: number): void {
    if (this.queue.length === 0) {
      this.carry = 0;
      return;
    }
    this.carry += (this.rate * Math.max(0, dtMs)) / 1000;
    let whole = Math.floor(this.carry);
    this.carry -= whole;
    if (whole === 0) return;
    while (whole > 0 && this.queue.length > 0) {
      const head = this.queue[0];
      const take = Math.min(whole, head.total - this.shown);
      this.shown += take;
      whole -= take;
      if (this.shown >= head.total) {
        this.queue.shift();
        this.shown = 0;
        this.revealedSegments += 1;
      }
    }
    if (this.queue.length === 0) this.carry = 0;
    this.cached = null;
  }

  /** The view for rendering. The same object is returned until the queue changes, so callers can compare by identity. */
  view(): RevealView {
    if (this.cached) return this.cached;
    const waiting = new Set<number>();
    for (let i = 1; i < this.queue.length; i++) waiting.add(this.queue[i].index);
    this.cached = {
      head: this.queue.length > 0 ? this.queue[0].index : null,
      shown: this.shown,
      waiting,
    };
    return this.cached;
  }
}
