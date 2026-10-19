// Pure helpers that turn run state into the strings and numbers the page shows.
// Nothing here touches React or the DOM.

import { DASH, formatClock, shortDeviceName } from "@/lib/format";
import type { LatencyStats, RunState } from "@/lib/live-state";
import type { RunStatus, RunSummary } from "@/lib/live-types";

/** Run picker value that follows the newest run. */
export const FOLLOW_NEWEST = "latest";

export const RUN_STATUS_WORD: Record<RunStatus, string> = {
  running: "Running",
  finished: "Finished",
  error: "Failed",
  canceled: "Canceled",
  stale: "Stopped",
};

/** Name of a run in the picker: its audio file, or its id when the file is unknown. */
export function runName(run: RunSummary): string {
  return run.audio_name || run.run_id;
}

/**
 * Loudness peaks under the segment that was transcribed last: the buckets whose
 * time span covers [start, end] once the file's start offset is removed.
 * Empty until both the peaks and the duration are known.
 */
export function envelopeFor(
  peaks: readonly number[] | null,
  duration: number | null,
  startOffset: number,
  segment: { start: number; end: number } | undefined,
): number[] {
  if (!peaks || peaks.length === 0 || !duration || duration <= 0 || !segment) return [];
  const n = peaks.length;
  const bucket = (seconds: number) => Math.min(1, Math.max(0, (seconds - startOffset) / duration)) * n;
  const first = Math.min(n - 1, Math.floor(bucket(segment.start)));
  const last = Math.min(n, Math.max(first + 1, Math.ceil(bucket(segment.end))));
  return peaks.slice(first, last);
}

/** "zh · 97%", or the bare language when no confidence was reported. Null until a language is known. */
export function languageText(run: RunState | null): string | null {
  if (!run?.language || run.language === "Auto") return null;
  if (run.languageProbability === null) return run.language;
  return `${run.language} · ${Math.round(run.languageProbability * 100)}%`;
}

/** "RTX 5060 Ti · CUDA", from the device name and the device kind. Null when neither is known. */
export function deviceText(run: RunState | null): string | null {
  const parts = [shortDeviceName(run?.deviceName), run?.device ? run.device.toUpperCase() : null];
  const shown = parts.filter((part): part is string => Boolean(part));
  return shown.length > 0 ? shown.join(" · ") : null;
}

/** Splits a path at its last separator so the directory can be cut while the file name stays. */
export function splitPath(path: string): { dir: string; file: string } {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut < 0 ? { dir: "", file: path } : { dir: path.slice(0, cut + 1), file: path.slice(cut + 1) };
}

const ms = (value: number) => `${Math.round(value)} ms`;

/** Hint for the latency tile: what is measured, then the last and median values. */
export function latencyHint(stats: LatencyStats): string {
  const intro = "Time from the CLI finishing a segment to it appearing here.";
  if (stats.last === null || stats.median === null) {
    return `${intro} Measured on segments that arrive while this page is open.`;
  }
  const split =
    stats.tail !== null && stats.push !== null ? ` (tail ${ms(stats.tail)} + push ${ms(stats.push)})` : "";
  return `${intro} Last ${ms(stats.last)} · median ${ms(stats.median)}${split}.`;
}

/** "01:12 of 03:23" for transcribed media seconds against the audio duration. */
export function clockText(transcribed: number | null, duration: number | null): string {
  if (transcribed === null) return DASH;
  return `${formatClock(transcribed)} of ${formatClock(duration)}`;
}
