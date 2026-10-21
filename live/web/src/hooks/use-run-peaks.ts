import { useEffect, useState } from "react";
import type { PeaksPayload } from "@/lib/live-types";

/**
 * Why a run has no waveform: its audio file is gone (`missing`), cannot be decoded (`undecodable`),
 * or the server kept failing (`failed`). Null when the peaks are loaded or not asked for yet.
 */
export type PeaksError = "missing" | "undecodable" | "failed" | null;

export interface RunPeaks {
  peaks: number[] | null;
  error: PeaksError;
}

interface PeaksEntry extends RunPeaks {
  runId: string;
  /** The `ended` flag in force when this entry was loaded. A failed load is retried once the run ends. */
  ended: boolean;
}

const NO_PEAKS: RunPeaks = { peaks: null, error: null };
/** Waits before each retry of a network error or 5xx: 1, 2, 4, 8, 16 s. Then the load gives up. */
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];

/**
 * Loudness peaks for a run, or why there are none. Requested as soon as the caller has a run id
 * (the server reads the input file, which exists from the start, so live runs get a waveform too).
 * 404 (no audio file) and 422 (audio cannot be decoded) are final and never retried. Network errors
 * and 5xx responses retry on RETRY_DELAYS_MS; after that the load fails until the run's `ended` flag changes.
 */
export function useRunPeaks(runId: string | null, ended: boolean): RunPeaks {
  const [entry, setEntry] = useState<PeaksEntry>({ runId: "", peaks: null, error: null, ended: false });

  useEffect(() => {
    if (!runId) return;
    // `entry` is the value from the render that scheduled this effect, which is the latest one.
    const sameRun = entry.runId === runId;
    if (sameRun && (entry.peaks || entry.error === "missing" || entry.error === "undecodable")) return;
    if (sameRun && entry.error === "failed" && entry.ended === ended) return;

    const ctrl = new AbortController();
    let retryTimer: number | undefined;

    const settle = (next: RunPeaks) => {
      if (!ctrl.signal.aborted) setEntry({ runId, ended, ...next });
    };

    const load = async (attempt: number): Promise<void> => {
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/peaks?n=1200`, { signal: ctrl.signal });
        if (res.ok) {
          const body = (await res.json()) as PeaksPayload;
          settle({ peaks: body.peaks, error: null });
        } else if (res.status === 404) {
          settle({ peaks: null, error: "missing" });
        } else if (res.status === 422) {
          settle({ peaks: null, error: "undecodable" });
        } else if (res.status >= 500) {
          throw new Error(`peaks ${res.status}`);
        } else {
          settle({ peaks: null, error: "failed" });
        }
      } catch {
        if (ctrl.signal.aborted) return;
        const delay = RETRY_DELAYS_MS[attempt];
        if (delay === undefined) settle({ peaks: null, error: "failed" });
        else retryTimer = window.setTimeout(() => void load(attempt + 1), delay);
      }
    };
    void load(0);
    return () => {
      ctrl.abort();
      window.clearTimeout(retryTimer);
    };
  }, [runId, ended, entry.runId, entry.peaks, entry.error, entry.ended]);

  if (!runId || entry.runId !== runId) return NO_PEAKS;
  return { peaks: entry.peaks, error: entry.error };
}
