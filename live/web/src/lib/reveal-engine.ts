/**
 * The reveal queue for one run: live segments type out one grapheme at a time, strictly in arrival order.
 *
 * Pure and clock-free: the caller passes the frame step (ms) to advance() and the arrival time (ms) each segment
 * carries. No React, no DOM, so it can be unit-tested with plain Node. The pacing constants are in reveal-rate.ts.
 *
 * Continuous mode (the default) follows the feed. The arrival average (an EMA of graphemes per second, measured over
 * the gaps between arrivals) sets the base rate; the rate rises when the backlog would take too long to drain, and it
 * moves at most FLOW.SLEW_PER_S per second. The other modes reveal at one fixed rate. Neither mode drops text on a
 * timer: a fixed mode only reports that it is behind (view().behind).
 */

import { BEHIND_S, FLOW, graphemeCount, PRESET_CPS, type RevealMode } from "./reveal-rate.ts";

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
  /** Indexes sync() held back (see sync): not queued and not drawn until a later sync releases them. */
  held: ReadonlySet<number>;
  /** Fixed modes only: the backlog would take longer than BEHIND_S at the chosen rate. A hint; nothing is flushed. */
  behind: boolean;
}

interface Item {
  index: number;
  total: number;
  arrivedAt: number;
}

function sameIndexes(a: ReadonlySet<number>, b: ReadonlySet<number>): boolean {
  if (a.size !== b.size) return false;
  for (const index of a) if (!b.has(index)) return false;
  return true;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

export class RevealEngine {
  /** The run the queue belongs to. undefined until the first reset. */
  runId: string | null | undefined = undefined;
  /** Segments fully revealed in the current run (flushed segments count as revealed). */
  revealedSegments = 0;
  /** Live segments queued in the current run. */
  arrivals = 0;
  /** Average of the arriving graphemes per second (EMA over the arrival gaps). null until two arrivals of the run. */
  arrivalEma: number | null = null;
  /** Speed mode in use. */
  mode: RevealMode = "continuous";
  /** Fixed rate of a fixed mode, graphemes per second. Continuous mode ignores it. */
  fixedCps: number = PRESET_CPS.normal;
  /** Reveal rate in use, graphemes per second. */
  rate: number = FLOW.DEFAULT_CPS * FLOW.K;
  /** True once run_end has been seen. The continuous tail then finishes within FLOW.TAIL_S. */
  ended = false;

  // Segment indexes already queued or shown. A segment is queued at most once per run, so a re-sent snapshot never replays.
  private seen = new Set<number>();
  private queue: Item[] = [];
  /** Graphemes of queue[0] already shown. */
  private shown = 0;
  /** Fractional graphemes carried from one frame to the next, so the speed is steady at any frame rate. */
  private carry = 0;
  private cached: RevealView | null = null;
  /** Indexes the last sync() held back. */
  private held = new Set<number>();
  /** Arrival time (ms) of the last live segment queued in this run. */
  private lastArrivalAt: number | null = null;

  /** Starts a run. Its current segments count as already shown, so nothing in them is queued. */
  reset(runId: string | null, segments: readonly RevealSegment[]): void {
    this.runId = runId;
    this.revealedSegments = 0;
    this.arrivals = 0;
    this.arrivalEma = null;
    this.lastArrivalAt = null;
    this.seen = new Set(segments.map((segment) => segment.index));
    this.queue = [];
    this.shown = 0;
    this.carry = 0;
    this.held = new Set();
    this.rate = FLOW.DEFAULT_CPS * FLOW.K;
    this.cached = null;
  }

  /** Sets the speed. `fixedCps` is the rate of a fixed mode; continuous mode ignores it. */
  setSpeed(mode: RevealMode, fixedCps: number): void {
    this.mode = mode;
    this.fixedCps = fixedCps;
    if (mode !== "continuous") this.rate = fixedCps;
    this.cached = null;
  }

  /** Records whether run_end has been seen. */
  setEnded(ended: boolean): void {
    this.ended = ended;
  }

  /**
   * Queues the live segments not seen before, in the order given. Segments that are not live are marked seen and never
   * queued. `ready` says whether a segment may be shown yet. A segment it refuses waits, and so does every unseen segment
   * after it, so the queue keeps arrival order; those indexes are listed in view().held. Pass the run's whole segment
   * list: the held set is rebuilt from it on every call.
   */
  sync(segments: readonly RevealSegment[], ready: (segment: RevealSegment) => boolean = () => true): void {
    const held = new Set<number>();
    for (const segment of segments) {
      if (this.seen.has(segment.index)) continue;
      if (held.size > 0 || !ready(segment)) {
        held.add(segment.index);
        continue;
      }
      this.seen.add(segment.index);
      if (!segment.live) continue;
      const total = graphemeCount(segment.text.trim());
      if (total === 0) continue;
      this.noteArrival(total, segment.recvAt);
      this.queue.push({ index: segment.index, total, arrivedAt: segment.recvAt });
      this.cached = null;
    }
    if (!sameIndexes(held, this.held)) {
      this.held = held;
      this.cached = null;
    }
  }

  /** Folds one arrival into the arrival average: graphemes over the gap since the previous arrival. */
  private noteArrival(total: number, at: number): void {
    this.arrivals += 1;
    if (this.lastArrivalAt !== null) {
      const gapS = clamp((at - this.lastArrivalAt) / 1000, FLOW.MIN_GAP_S, FLOW.MAX_GAP_S);
      const sample = total / gapS;
      this.arrivalEma = this.arrivalEma === null ? sample : this.arrivalEma + FLOW.ALPHA * (sample - this.arrivalEma);
    }
    this.lastArrivalAt = at;
  }

  /** Graphemes still to show across the whole queue: the head's shown part is not counted. */
  backlogGraphemes(): number {
    let total = -this.shown;
    for (const item of this.queue) total += item.total;
    return total;
  }

  /** Shows everything queued at once. Returns how many graphemes that made visible. */
  flush(): number {
    let added = 0;
    while (this.queue.length > 0) {
      added += this.queue[0].total - this.shown;
      this.finishHead();
    }
    this.carry = 0;
    return added;
  }

  /** Shows the head segment in full and drops it from the queue. */
  private finishHead(): void {
    this.queue.shift();
    this.shown = 0;
    this.revealedSegments += 1;
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

  /**
   * Moves the reveal forward by `dtMs` of wall-clock time and returns how many graphemes became visible. Continuous
   * mode first updates its rate (stepContinuousRate); a fixed mode uses its chosen rate as it is.
   */
  advance(dtMs: number): number {
    if (this.queue.length === 0) {
      this.carry = 0;
      return 0;
    }
    const dtS = Math.max(0, dtMs) / 1000;
    if (this.mode === "continuous") {
      const backlog = this.backlogGraphemes();
      this.stepContinuousRate(backlog, dtS);
      // Safety only: a backlog that would take this long to show is shown at once.
      if (backlog / this.rate > FLOW.SAFETY_FLUSH_S) return this.flush();
    } else {
      this.rate = this.fixedCps;
    }
    this.carry += this.rate * dtS;
    let whole = Math.floor(this.carry);
    this.carry -= whole;
    let added = 0;
    while (whole > 0 && this.queue.length > 0) {
      const head = this.queue[0];
      const take = Math.min(whole, head.total - this.shown);
      this.shown += take;
      whole -= take;
      added += take;
      if (this.shown >= head.total) this.finishHead();
    }
    if (this.queue.length === 0) this.carry = 0;
    if (added > 0) this.cached = null;
    return added;
  }

  /**
   * Continuous mode: moves the rate toward its target by at most the slew limit. The base is the arrival average times
   * K, never below MIN_CPS. The target is raised to backlog / TARGET_S when the backlog is large, and lowered toward
   * the base (times DRY_FACTOR) when the queue runs dry. After run_end the target is the current rate or backlog /
   * TAIL_S, whichever is larger, with the faster tail slew.
   */
  private stepContinuousRate(backlog: number, dtS: number): void {
    const base = clamp((this.arrivalEma ?? FLOW.DEFAULT_CPS) * FLOW.K, FLOW.MIN_CPS, FLOW.MAX_CPS);
    let target = Math.max(base, backlog / FLOW.TARGET_S);
    if (backlog <= FLOW.DRY_GRAPHEMES) target = Math.min(target, base * FLOW.DRY_FACTOR);
    let slew: number = FLOW.SLEW_PER_S;
    let ceiling: number = FLOW.MAX_CPS;
    if (this.ended) {
      target = Math.max(this.rate, backlog / FLOW.TAIL_S);
      slew = FLOW.TAIL_SLEW_PER_S;
      ceiling = FLOW.TAIL_MAX_CPS;
    }
    const step = slew * dtS;
    const limited = clamp(target, this.rate * (1 - step), this.rate * (1 + step));
    this.rate = clamp(limited, FLOW.MIN_CPS, ceiling);
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
      held: this.held,
      behind: this.mode !== "continuous" && this.queue.length > 0 && this.backlogGraphemes() / this.fixedCps > BEHIND_S,
    };
    return this.cached;
  }
}
