// Which composition App shows: the pre-roll until a live run's four stats are known, a short morph into the
// full UI, then the full UI for good. Runs that are not live, or whose stats were known at first sight, open
// straight in the full UI. Exposes window.__nslivePreroll for tests.
import { useEffect, useState } from "react";
import { isRunActive, type RunState } from "@/lib/live-state";
import { prerollReady } from "@/lib/preroll-log";

export type PrerollMode = "pre" | "morph" | "full";
export type PrerollReason = "waiting" | "pre-roll" | "ready" | "known-at-mount" | "not-live" | "ended";

export interface PrerollMachine {
  runId: string | null;
  mode: PrerollMode;
  reason: PrerollReason;
  enteredAt: number | null;
  exitedAt: number | null;
  /** When the four stats were first known while the pre-roll shows. The switch may wait for the typing from there. */
  readyAt: number | null;
  /** The switch started with the terminal idle (false: the hold reached HOLD_CAP_MS first, or no hold applied). */
  settled: boolean;
}

export interface PrerollProbe {
  active: boolean;
  enteredAt: number | null;
  exitedAt: number | null;
  reason: PrerollReason;
  readyAt: number | null;
  settled: boolean;
}

declare global {
  interface Window {
    __nslivePreroll?: PrerollProbe;
  }
}

/** The orb's flight from the pre-roll to the stage card, in ms (ease-in-out). */
export const FLIGHT_MS = 900;
/** The orb hand-off after the flight: the flying clone fades out while the real orb fades in on the stage card, in ms. */
export const HANDOFF_MS = 150;
/** The rest of the terminal fades out in this many ms before the stat lines fly. */
export const TERMINAL_FADE_MS = 250;
/** The switch waits for the terminal's last line to finish typing, but at most this long after the stats are known. */
export const HOLD_CAP_MS = 3000;
/** Length of the morph into the full UI, in ms: the flight, the stat lines' flight, then the hand-over. */
export const MORPH_MS = 1150;
/** Reduced motion and easy view: a short crossfade, no flight. */
export const REDUCED_MORPH_MS = 200;

const IDLE: PrerollMachine = {
  runId: null,
  mode: "full",
  reason: "waiting",
  enteredAt: null,
  exitedAt: null,
  readyAt: null,
  settled: false,
};

/**
 * Pure transition: the machine after the shown run changed or its stats moved. Returns `m` itself when nothing changed.
 * `typingIdle`: the terminal has finished typing the shown run's lines. Until then a ready run holds the pre-roll.
 */
export function advancePreroll(
  m: PrerollMachine,
  run: RunState | null,
  now: number,
  typingIdle: boolean,
): PrerollMachine {
  if (!run) return m.runId === null ? m : IDLE;
  if (run.runId !== m.runId) {
    if (isRunActive(run) && !prerollReady(run)) {
      return { ...IDLE, runId: run.runId, mode: "pre", reason: "pre-roll", enteredAt: now };
    }
    const reason: PrerollReason = prerollReady(run) ? "known-at-mount" : "not-live";
    return { ...IDLE, runId: run.runId, mode: "full", reason };
  }
  if (m.mode === "pre") {
    if (prerollReady(run)) {
      const readyAt = m.readyAt ?? now;
      if (typingIdle || now - readyAt >= HOLD_CAP_MS) {
        return { ...m, mode: "morph", reason: "ready", exitedAt: now, readyAt, settled: typingIdle };
      }
      return m.readyAt === null ? { ...m, readyAt } : m;
    }
    if (!isRunActive(run)) return { ...m, mode: "full", reason: "ended", exitedAt: now };
  }
  return m;
}

/**
 * The composition to show for `run`. `easy` skips the morph; reduced motion shortens it to a crossfade. Neither waits
 * for the typing: `typingIdle` only gates the switch in the full motion view.
 */
export function usePrerollMode(
  run: RunState | null,
  easy: boolean,
  reduce: boolean,
  now: number,
  typingIdle: boolean,
): PrerollMachine {
  const [stored, setStored] = useState<PrerollMachine>(IDLE);
  const current = advancePreroll(stored, run, now, typingIdle || easy || reduce);
  // Store from render: a new run or a moved stat takes effect in this same render, with no frame of the old view.
  if (current !== stored) setStored(current);

  useEffect(() => {
    if (current.mode !== "morph") return;
    const delay = easy ? 0 : reduce ? REDUCED_MORPH_MS : MORPH_MS;
    const id = window.setTimeout(() => {
      setStored((prev) => (prev.mode === "morph" ? { ...prev, mode: "full" } : prev));
    }, delay);
    return () => window.clearTimeout(id);
  }, [current.mode, easy, reduce]);

  useEffect(() => {
    window.__nslivePreroll = {
      active: current.mode === "pre",
      enteredAt: current.enteredAt,
      exitedAt: current.exitedAt,
      reason: current.reason,
      readyAt: current.readyAt,
      settled: current.settled,
    };
  }, [current]);

  return current;
}
