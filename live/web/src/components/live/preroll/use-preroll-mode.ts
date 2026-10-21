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
}

export interface PrerollProbe {
  active: boolean;
  enteredAt: number | null;
  exitedAt: number | null;
  reason: PrerollReason;
}

declare global {
  interface Window {
    __nslivePreroll?: PrerollProbe;
  }
}

/** Length of the morph into the full UI, in ms (reduced motion crossfades in 300 ms). */
export const MORPH_MS = 1100;
const REDUCED_MORPH_MS = 300;

const IDLE: PrerollMachine = { runId: null, mode: "full", reason: "waiting", enteredAt: null, exitedAt: null };

/** Pure transition: the machine after the shown run changed or its stats moved. Returns `m` itself when nothing changed. */
export function advancePreroll(m: PrerollMachine, run: RunState | null, now: number): PrerollMachine {
  if (!run) return m.runId === null ? m : IDLE;
  if (run.runId !== m.runId) {
    if (isRunActive(run) && !prerollReady(run)) {
      return { runId: run.runId, mode: "pre", reason: "pre-roll", enteredAt: now, exitedAt: null };
    }
    const reason: PrerollReason = prerollReady(run) ? "known-at-mount" : "not-live";
    return { runId: run.runId, mode: "full", reason, enteredAt: null, exitedAt: null };
  }
  if (m.mode === "pre") {
    if (prerollReady(run)) return { ...m, mode: "morph", reason: "ready", exitedAt: now };
    if (!isRunActive(run)) return { ...m, mode: "full", reason: "ended", exitedAt: now };
  }
  return m;
}

/** The composition to show for `run`. `easy` skips the morph; reduced motion shortens it to a crossfade. */
export function usePrerollMode(run: RunState | null, easy: boolean, reduce: boolean, now: number): PrerollMachine {
  const [stored, setStored] = useState<PrerollMachine>(IDLE);
  const current = advancePreroll(stored, run, now);
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
    };
  }, [current]);

  return current;
}
