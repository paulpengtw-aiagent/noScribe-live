// Pure helpers that turn run state into the strings and numbers the page shows.
// Nothing here touches React or the DOM.

import { catalog } from "@/i18n/catalog";
import type { Locale } from "@/i18n/core";
import { DASH, formatClock, shortDeviceName } from "@/lib/format";
import { isRunActive, type LatencyStats, type RunState } from "@/lib/live-state";
import type { RunStatus, RunSummary } from "@/lib/live-types";

/** Run picker value that follows the newest run. */
export const FOLLOW_NEWEST = "latest";

/** Name of a run in the picker: its audio file, or its id when the file is unknown. */
export function runName(run: RunSummary): string {
  return run.audio_name || run.run_id;
}

/** True while the server reports a run as running. */
export function isLiveSummary(run: RunSummary): boolean {
  return run.live === true || run.status === "running";
}

/**
 * The newest run other than the one shown that is still running. Null when following
 * and the shown run is live (the server already picked it), so no hint is needed.
 */
export function otherLiveRun(
  runs: readonly RunSummary[],
  shownRunId: string | null,
  shownLive: boolean,
  following: boolean,
): RunSummary | null {
  if (following && shownLive) return null;
  let newest: RunSummary | null = null;
  for (const run of runs) {
    if (run.run_id === shownRunId || !isLiveSummary(run)) continue;
    if (!newest || (run.started_t ?? -Infinity) > (newest.started_t ?? -Infinity)) newest = run;
  }
  return newest;
}

/**
 * Header badge key for the selected run: "running" while it runs, else how it stopped. The caller maps
 * the key to a catalog label. Null with no run.
 */
export function runStateBadge(run: RunState | null): { status: RunStatus } | null {
  if (!run) return null;
  if (isRunActive(run)) return { status: "running" };
  return { status: run.endStatus ?? "stale" };
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

/** Hint for the latency tile: what is measured, then the last and median values. Text comes from the catalog. */
export function latencyHint(stats: LatencyStats, locale: Locale = "en"): string {
  const words = catalog[locale].topbar.latency;
  if (stats.last === null || stats.median === null) return words.noSamples;
  const split = stats.tail !== null && stats.push !== null ? words.split(ms(stats.tail), ms(stats.push)) : "";
  return words.stats(ms(stats.last), ms(stats.median), split);
}

/** "01:12 of 03:23" (zh: "01:12 / 03:23") for transcribed media seconds against the audio duration. */
export function clockText(transcribed: number | null, duration: number | null, locale: Locale = "en"): string {
  if (transcribed === null) return DASH;
  return catalog[locale].topbar.clockOf(formatClock(transcribed), formatClock(duration));
}
