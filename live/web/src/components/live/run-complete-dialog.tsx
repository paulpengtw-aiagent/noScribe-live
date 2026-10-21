// Opens once when a run this page was showing live finishes successfully. It never opens for a run that was already
// finished when first shown, nor for a run that failed, stopped or was canceled. The UI is a lazy chunk
// (run-complete-dialog-view.tsx), so the entry bundle carries only this detection.
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { isRunActive, type RunState } from "@/lib/live-state";

const RunCompleteView = lazy(() => import("@/components/live/run-complete-dialog-view"));

/** sessionStorage key: the run ids this tab has already announced, as a JSON array with the newest last. */
export const RUN_COMPLETE_SEEN_KEY = "noscribe-live-run-complete";
const SEEN_LIMIT = 50;

/** The figures shown in the dialog, frozen at the finish so a later switch of run does not change them. */
export interface RunCompleteSummary {
  runId: string;
  duration: number | null;
  segments: number;
  speakers: number;
}

function readSeen(): string[] {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(RUN_COMPLETE_SEEN_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    // Storage can be unavailable or hold bad JSON; the in-memory set still stops a repeat for this page view.
    return [];
  }
}

function rememberSeen(runId: string): void {
  try {
    const ids = [...readSeen().filter((id) => id !== runId), runId].slice(-SEEN_LIMIT);
    sessionStorage.setItem(RUN_COMPLETE_SEEN_KEY, JSON.stringify(ids));
  } catch {
    // Storage can be unavailable; the in-memory set still stops a repeat for this page view.
  }
}

/**
 * The run's finish, announced once. A run counts as watched live when the page shows it while it is still running,
 * so a finish is announced only when it arrives while that same run stays on screen. Opening a finished run from
 * history, or switching back to one that finished meanwhile, stays quiet.
 */
export function RunCompleteDialog({ run }: { run: RunState | null }) {
  const [summary, setSummary] = useState<RunCompleteSummary | null>(null);
  const [open, setOpen] = useState(false);
  // The run on screen and whether it was live when this page first showed it.
  const shown = useRef<{ runId: string; live: boolean } | null>(null);
  const announced = useRef(new Set<string>());

  useEffect(() => {
    if (!run) {
      shown.current = null;
      return;
    }
    const prev = shown.current;
    if (prev === null || prev.runId !== run.runId) {
      shown.current = { runId: run.runId, live: isRunActive(run) };
      return;
    }
    if (isRunActive(run)) {
      prev.live = true;
      return;
    }
    if (!prev.live || run.endStatus !== "finished") return;
    if (announced.current.has(run.runId) || readSeen().includes(run.runId)) return;
    announced.current.add(run.runId);
    rememberSeen(run.runId);
    setSummary({
      runId: run.runId,
      duration: run.duration,
      segments: run.segments.length,
      speakers: run.speakers.length,
    });
    setOpen(true);
  }, [run]);

  if (!summary) return null;

  return (
    <Suspense fallback={null}>
      <RunCompleteView summary={summary} open={open} onOpenChange={setOpen} />
    </Suspense>
  );
}
