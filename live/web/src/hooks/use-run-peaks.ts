import { useEffect, useState } from "react";
import type { PeaksPayload } from "@/lib/live-types";

/**
 * Why a run has no waveform: its audio file is gone (`missing`), cannot be decoded (`undecodable`),
 * or the request failed for another reason (`failed`). Null when the peaks are loaded or not asked for yet.
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
const RETRY_MS = 2000;

/**
 * Loudness peaks for a run, or why there are none. 404 (no audio file) and 422 (audio cannot be decoded)
 * are final and never retried. Any other failure retries once after 2 s, and again when the run ends.
 */
export function useRunPeaks(runId: string | null, ended: boolean): RunPeaks {
  const [entry, setEntry] = useState<PeaksEntry>({ runId: "", peaks: null, error: null, ended: false });

  useEffect(() => {
    if (!runId) return;
    // `entry` is the value from the render that scheduled this effect, which is the latest one.
    const final = entry.error === "missing" || entry.error === "undecodable";
    const failedThisEnd = entry.error === "failed" && entry.ended === ended;
    if (entry.runId === runId && (entry.peaks || final || failedThisEnd)) return;

    const ctrl = new AbortController();
    let retryTimer: number | undefined;
    let retried = false;

    const settle = (next: RunPeaks) => {
      if (!ctrl.signal.aborted) setEntry({ runId, ended, ...next });
    };

    const load = async (): Promise<void> => {
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/peaks?n=1200`, { signal: ctrl.signal });
        if (res.ok) {
          const body = (await res.json()) as PeaksPayload;
          settle({ peaks: body.peaks, error: null });
        } else if (res.status === 404) {
          settle({ peaks: null, error: "missing" });
        } else if (res.status === 422) {
          settle({ peaks: null, error: "undecodable" });
        } else {
          throw new Error(`peaks ${res.status}`);
        }
      } catch {
        if (ctrl.signal.aborted) return;
        if (!retried) {
          retried = true;
          retryTimer = window.setTimeout(() => void load(), RETRY_MS);
          return;
        }
        settle({ peaks: null, error: "failed" });
      }
    };
    void load();
    return () => {
      ctrl.abort();
      window.clearTimeout(retryTimer);
    };
  }, [runId, ended, entry.runId, entry.peaks, entry.error, entry.ended]);

  if (!runId || entry.runId !== runId) return NO_PEAKS;
  return { peaks: entry.peaks, error: entry.error };
}
