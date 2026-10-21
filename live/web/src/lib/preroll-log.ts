// Pure helpers for the cinematic pre-roll: which terminal lines a run has earned so far, and when the four
// stats (model, device, language, speaker count) are known. No React, no DOM, no i18n: the view formats the
// lines with the catalog. Every value comes from the run state the live reducer built from the feed.
import type { RunState } from "@/lib/live-state";

export type PrerollLineId =
  | "audio"
  | "convert"
  | "segmentation"
  | "embeddings"
  | "speakers"
  | "model"
  | "device"
  | "language"
  | "firstSegment";

export type PrerollText =
  | { kind: "audio"; name: string; duration: number | null }
  | { kind: "convert" }
  | { kind: "detect"; step: "segmentation" | "embeddings"; pct: number | null }
  | { kind: "speakers"; count: number }
  | { kind: "model"; model: string }
  | {
      kind: "device";
      name: string | null;
      device: string | null;
      computeType: string | null;
      loadSeconds: number | null;
    }
  | { kind: "language"; code: string; percent: number | null }
  | { kind: "firstSegment" };

/** One terminal row. `id` is stable for the life of the run: a row that changes updates in place under the same id. */
export interface PrerollLine {
  id: PrerollLineId;
  state: "running" | "done";
  text: PrerollText;
}

const PHASE_RANK: Record<string, number> = { converting: 0, diarizing: 1, transcribing: 2 };

/**
 * True once all four stats are known: the model name, the model's device (loaded), the language and the speaker
 * count. The speaker count counts as known with the first segment, for a run that reports no speakers at all.
 */
export function prerollReady(run: RunState | null): boolean {
  if (!run) return false;
  return (
    run.model !== null &&
    run.modelReady &&
    (run.deviceName !== null || run.device !== null) &&
    run.language !== null &&
    (run.speakers.length > 0 || run.segments.length > 0)
  );
}

/**
 * The terminal rows a run has earned so far, in the order they appear. Nothing is invented: a step with no
 * feed data yields no row, and a value the feed did not send is left out of its row.
 */
export function prerollLines(run: RunState | null): PrerollLine[] {
  if (!run || run.startedT === null) return [];
  const lines: PrerollLine[] = [];
  if (run.audioName) {
    lines.push({ id: "audio", state: "done", text: { kind: "audio", name: run.audioName, duration: run.duration } });
  }
  // Converting runs until the next phase starts. A run with no phase yet is still converting.
  const converting = run.phase === null || PHASE_RANK[run.phase] === 0;
  lines.push({ id: "convert", state: converting ? "running" : "done", text: { kind: "convert" } });

  const diarized = run.speakers.length > 0;
  const segmenting = run.progress?.detail === "segmentation";
  const embedding = run.progress?.detail === "embeddings";
  const pct = run.progress?.pct ?? null;
  if (segmenting || embedding || diarized) {
    lines.push({
      id: "segmentation",
      state: segmenting ? "running" : "done",
      text: { kind: "detect", step: "segmentation", pct: segmenting ? pct : null },
    });
  }
  if (embedding || diarized) {
    lines.push({
      id: "embeddings",
      state: diarized ? "done" : "running",
      text: { kind: "detect", step: "embeddings", pct: embedding ? pct : null },
    });
  }
  if (diarized) lines.push({ id: "speakers", state: "done", text: { kind: "speakers", count: run.speakers.length } });

  const model = run.model;
  if (model !== null && (diarized || run.modelReady || run.segments.length > 0 || run.phase === "transcribing")) {
    lines.push({ id: "model", state: run.modelReady ? "done" : "running", text: { kind: "model", model } });
  }
  if (
    run.modelReady &&
    (run.deviceName !== null || run.device !== null || run.computeType !== null || run.modelLoadSeconds !== null)
  ) {
    lines.push({
      id: "device",
      state: "done",
      text: {
        kind: "device",
        name: run.deviceName,
        device: run.device,
        computeType: run.computeType,
        loadSeconds: run.modelLoadSeconds,
      },
    });
  }
  if (run.language !== null) {
    const percent = run.languageProbability === null ? null : Math.round(run.languageProbability * 100);
    lines.push({ id: "language", state: "done", text: { kind: "language", code: run.language, percent } });
  }
  if (run.segments.length > 0) lines.push({ id: "firstSegment", state: "done", text: { kind: "firstSegment" } });
  return lines;
}

/** Audio length as m:ss, rounded to the second. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** A fixed-width progress bar with block cells, e.g. "▕████░░░░▏" for 42 percent. */
export function barText(pct: number, cells = 8): string {
  const clamped = Math.min(100, Math.max(0, pct));
  const filled = Math.round((clamped / 100) * cells);
  return `▕${"█".repeat(filled)}${"░".repeat(cells - filled)}▏`;
}

/** Seconds as mm:ss, minutes padded to two digits. */
export function clockText(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** The percentage a progress message carries (e.g. "Transcribing 42%"), or null when it carries none. */
export function progressPct(msg: string): number | null {
  const match = /(\d+(?:\.\d+)?)\s*%/.exec(msg);
  return match ? Math.min(100, Math.max(0, Number(match[1]))) : null;
}

/** An item with the sort key it takes in the merged terminal. */
export interface Keyed<T> {
  item: T;
  key: number;
}

/**
 * Merges two lists that are each in time order. The steps keep their order; a log line goes before the first step
 * whose key is above the line's key, so a line that arrived before a step shows above it.
 */
export function interleave<T>(steps: readonly Keyed<T>[], logs: readonly Keyed<T>[]): T[] {
  const out: T[] = [];
  let j = 0;
  for (const step of steps) {
    while (j < logs.length && logs[j].key < step.key) out.push(logs[j++].item);
    out.push(step.item);
  }
  while (j < logs.length) out.push(logs[j++].item);
  return out;
}
