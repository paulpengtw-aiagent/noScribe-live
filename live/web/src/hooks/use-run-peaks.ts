import { useEffect, useState } from "react";
import type { PeaksPayload } from "@/lib/live-types";

interface PeaksEntry {
  runId: string;
  peaks: number[] | null;
}

/**
 * Loudness peaks for a run. 404 means "not available yet": retry once after
 * 2 s, and again when the run ends, since the file may appear by then.
 */
export function useRunPeaks(runId: string | null, ended: boolean): number[] | null {
  const [entry, setEntry] = useState<PeaksEntry>({ runId: "", peaks: null });

  useEffect(() => {
    if (!runId) return;
    // `entry` is the value from the render that scheduled this effect, which is the latest one.
    if (entry.runId === runId && entry.peaks) return;
    const ctrl = new AbortController();
    let retryTimer: number | undefined;
    let retried = false;

    const load = async () => {
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/peaks?n=1200`, { signal: ctrl.signal });
        if (!res.ok) throw new Error(`peaks ${res.status}`);
        const body = (await res.json()) as PeaksPayload;
        if (!ctrl.signal.aborted) setEntry({ runId, peaks: body.peaks });
      } catch {
        if (ctrl.signal.aborted) return;
        if (!retried) {
          retried = true;
          retryTimer = window.setTimeout(load, 2000);
        }
      }
    };
    void load();
    return () => {
      ctrl.abort();
      window.clearTimeout(retryTimer);
    };
  }, [runId, ended, entry.runId, entry.peaks]);

  return runId && entry.runId === runId ? entry.peaks : null;
}
