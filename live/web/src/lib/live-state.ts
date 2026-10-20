// Pure reducer and selectors for one live run. No React in here: the hooks
// feed it events and read the derived values. `now` is always passed in so
// the reducer stays deterministic.

import type { FeedEvent, RunStatus, RunSummary } from "@/lib/live-types";
import { speakerKey } from "@/lib/speakers";

export type EndStatus = "finished" | "error" | "canceled";

export type DisplayPhase =
  | "waiting"
  | "converting"
  | "diarizing"
  | "loading"
  | "listening"
  | "transcribing"
  | "finished"
  | "error"
  | "canceled";

export interface Segment {
  index: number;
  /** Feed `seq` of the segment event that wrote it; -1 when the event carries none. */
  seq: number;
  start: number;
  end: number;
  speaker: string;
  text: string;
  /** CLI write time, unix seconds. */
  t: number;
  /** Server read time, unix seconds; null when not stamped. */
  serverT: number | null;
  /** Date.now() when this page processed the segment. */
  recvAt: number;
  /** True only when the segment arrived through a `feed` event, not a snapshot. */
  live: boolean;
}

export interface RunProgress {
  phase: string;
  pct: number;
  detail: string | null;
}

export interface RunState {
  runId: string;
  audioName: string | null;
  audioFile: string | null;
  outputFile: string | null;
  model: string | null;
  languageName: string | null;
  language: string | null;
  languageProbability: number | null;
  speakerDetection: string | null;
  phase: string | null;
  progress: RunProgress | null;
  duration: number | null;
  startOffset: number;
  speakers: string[];
  device: string | null;
  deviceName: string | null;
  computeType: string | null;
  modelLoadSeconds: number | null;
  modelReady: boolean;
  segments: Segment[];
  /** Live segments received on this page; drives the orb pulse. */
  liveCount: number;
  startedT: number | null;
  endedT: number | null;
  endStatus: EndStatus | null;
  error: string | null;
  elapsed: number | null;
  /** The server reports the run as stale: it died without writing run_end. */
  stale: boolean;
  /** Server's inferred end for a stale run (its last event time); null otherwise. */
  inferredEndT: number | null;
  /** Basename of the output HTML from the server summary; null until that file exists. */
  outputName: string | null;
  /** `t` of the last applied event; the stop time of a stale run that has no inferred end. */
  lastT: number | null;
  /** Highest feed `seq` applied so far (-1 before any). Lines at or below it are duplicates. */
  lastSeq: number;
}

export interface LiveState {
  runs: RunSummary[];
  serverT: number | null;
  run: RunState | null;
}

export type LiveAction =
  | { type: "reset" }
  | { type: "hello"; serverT: number; runs: RunSummary[] }
  | { type: "runs"; runs: RunSummary[] }
  | { type: "snapshot"; runId: string | null; summary: RunSummary | null; events: FeedEvent[]; now: number }
  | { type: "feed"; runId: string; event: FeedEvent; now: number };

export const INITIAL_LIVE_STATE: LiveState = { runs: [], serverT: null, run: null };

function endFromStatus(status: RunStatus | undefined): EndStatus | null {
  return status === "finished" || status === "error" || status === "canceled" ? status : null;
}

function emptyRun(runId: string, summary: RunSummary | null): RunState {
  return {
    runId,
    audioName: summary?.audio_name ?? null,
    audioFile: null,
    outputFile: null,
    model: summary?.model ?? null,
    languageName: null,
    language: summary?.language ?? null,
    languageProbability: null,
    speakerDetection: null,
    phase: null,
    progress: null,
    duration: summary?.duration ?? null,
    startOffset: 0,
    speakers: [],
    device: summary?.device ?? null,
    deviceName: summary?.device_name ?? null,
    computeType: null,
    modelLoadSeconds: null,
    modelReady: false,
    segments: [],
    liveCount: 0,
    startedT: summary?.started_t ?? null,
    endedT: summary?.ended_t ?? null,
    endStatus: endFromStatus(summary?.status),
    error: null,
    elapsed: null,
    stale: summary?.status === "stale",
    inferredEndT: summary?.inferred_end_t ?? null,
    outputName: summary?.output_name ?? null,
    lastT: null,
    lastSeq: -1,
  };
}

function mergeSpeakers(current: string[], incoming: readonly string[]): string[] {
  let next = current;
  for (const raw of incoming) {
    const key = speakerKey(raw);
    if (key && !next.includes(key)) next = [...next, key];
  }
  return next;
}

function applyEvent(run: RunState, ev: FeedEvent, ctx: { now: number; live: boolean }): RunState {
  switch (ev.type) {
    case "run_start":
      return {
        ...run,
        audioFile: ev.audio_file,
        audioName: basenameOf(ev.audio_file) ?? run.audioName,
        outputFile: ev.output_file ?? run.outputFile,
        model: ev.model ?? run.model,
        languageName: ev.language ?? run.languageName,
        speakerDetection: ev.speaker_detection ?? run.speakerDetection,
        startedT: ev.t,
      };
    case "phase":
      return { ...run, phase: ev.phase, progress: run.phase === ev.phase ? run.progress : null };
    case "progress":
      return {
        ...run,
        phase: ev.phase,
        progress: { phase: ev.phase, pct: ev.pct, detail: ev.detail ?? null },
      };
    case "audio":
      return { ...run, duration: ev.duration, startOffset: ev.start_offset ?? 0 };
    case "diarization":
      return { ...run, speakers: mergeSpeakers(run.speakers, ev.speakers) };
    case "model_ready":
      return {
        ...run,
        modelReady: true,
        device: ev.device ?? run.device,
        deviceName: ev.device_name ?? run.deviceName,
        computeType: ev.compute_type ?? run.computeType,
        modelLoadSeconds: ev.load_seconds ?? run.modelLoadSeconds,
      };
    case "language":
      return { ...run, language: ev.language ?? run.language, languageProbability: ev.probability ?? null };
    case "segment": {
      const seg: Segment = {
        index: ev.index,
        seq: typeof ev.seq === "number" ? ev.seq : -1,
        start: ev.start,
        end: ev.end,
        speaker: ev.speaker ?? "",
        text: ev.text ?? "",
        t: ev.t,
        serverT: ev.server_t ?? null,
        recvAt: ctx.now,
        live: ctx.live,
      };
      const last = run.segments[run.segments.length - 1];
      let segments: Segment[];
      let isNew = true;
      if (!last || seg.index > last.index) {
        segments = [...run.segments, seg];
      } else {
        const pos = run.segments.findIndex((s) => s.index === seg.index);
        if (pos >= 0) {
          segments = run.segments.map((s, i) => (i === pos ? seg : s));
          isNew = false;
        } else {
          segments = [...run.segments, seg].sort((a, b) => a.index - b.index);
        }
      }
      return {
        ...run,
        segments,
        speakers: mergeSpeakers(run.speakers, [seg.speaker]),
        liveCount: ctx.live && isNew ? run.liveCount + 1 : run.liveCount,
      };
    }
    case "run_end":
      return {
        ...run,
        endStatus: ev.status,
        error: ev.error ?? null,
        outputFile: ev.output_file ?? run.outputFile,
        elapsed: ev.elapsed ?? null,
        endedT: ev.t,
      };
    default:
      return run;
  }
}

function basenameOf(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** applyEvent plus the bookkeeping for dedupe (lastSeq) and the stop-time fallback (lastT). */
function applyLine(run: RunState, ev: FeedEvent, ctx: { now: number; live: boolean }): RunState {
  const next = applyEvent(run, ev, ctx);
  return {
    ...next,
    lastSeq: typeof ev.seq === "number" ? Math.max(run.lastSeq, ev.seq) : run.lastSeq,
    lastT: typeof ev.t === "number" ? ev.t : run.lastT,
  };
}

/** Copies the server's view of a run (stale, end, inferred end, output name) onto its state. Returns `run` itself when nothing changed. */
function withSummary(run: RunState, summary: RunSummary): RunState {
  const stale = summary.status === "stale";
  const endStatus = run.endStatus ?? endFromStatus(summary.status);
  const endedT = run.endedT ?? summary.ended_t ?? null;
  const inferredEndT = summary.inferred_end_t ?? null;
  const outputName = summary.output_name ?? null;
  if (
    run.stale === stale &&
    run.endStatus === endStatus &&
    run.endedT === endedT &&
    run.inferredEndT === inferredEndT &&
    run.outputName === outputName
  ) {
    return run;
  }
  return { ...run, stale, endStatus, endedT, inferredEndT, outputName };
}

/** Carries the server's view of the followed run into `state.run`. */
function applyRunSummaries(state: LiveState, runs: RunSummary[]): LiveState {
  const run = state.run;
  if (!run) return state;
  const summary = runs.find((r) => r.run_id === run.runId);
  if (!summary) return state;
  const next = withSummary(run, summary);
  return next === run ? state : { ...state, run: next };
}

/**
 * A snapshot for the run already on screen (the stream reconnected) rebuilds the run
 * from its events. Keep the segment objects that did not change, so their reveal
 * state survives, and keep the pulse counter so the orb does not jump.
 */
function keepRevealState(previous: RunState, next: RunState): RunState {
  const before = new Map(previous.segments.map((seg) => [seg.index, seg]));
  const segments = next.segments.map((seg) => {
    const old = before.get(seg.index);
    const same =
      old !== undefined && old.start === seg.start && old.end === seg.end && old.speaker === seg.speaker && old.text === seg.text;
    return same ? old : seg;
  });
  return { ...next, segments, liveCount: previous.liveCount, lastSeq: Math.max(previous.lastSeq, next.lastSeq) };
}

export function liveReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.type) {
    case "reset":
      return { ...state, run: null };
    case "hello":
      return applyRunSummaries({ ...state, runs: action.runs, serverT: action.serverT }, action.runs);
    case "runs":
      return applyRunSummaries({ ...state, runs: action.runs }, action.runs);
    case "snapshot": {
      if (!action.runId) return { ...state, run: null };
      const summary = action.summary ?? state.runs.find((r) => r.run_id === action.runId) ?? null;
      let run = emptyRun(action.runId, summary);
      for (const ev of action.events) run = applyLine(run, ev, { now: action.now, live: false });
      const previous = state.run && state.run.runId === action.runId ? state.run : null;
      return { ...state, run: previous ? keepRevealState(previous, run) : run };
    }
    case "feed": {
      // Events for a run we are not following are ignored; the server sends a
      // fresh snapshot whenever the followed run changes.
      if (!state.run || state.run.runId !== action.runId) return state;
      // Already applied (for example replayed after a reconnect): drop it.
      if (action.event.seq <= state.run.lastSeq) return state;
      return { ...state, run: applyLine(state.run, action.event, { now: action.now, live: true }) };
    }
    default:
      return state;
  }
}

// ---------------------------------------------------------------- selectors

export function displayPhase(run: RunState | null): DisplayPhase {
  if (!run) return "waiting";
  if (run.endStatus) return run.endStatus;
  if (run.stale) return "error";
  if (run.segments.length > 0) return "transcribing";
  if (run.phase === "diarizing") return "diarizing";
  if (run.phase === "transcribing") return run.modelReady ? "listening" : "loading";
  return "converting";
}

export const PHASE_LABEL: Record<DisplayPhase, string> = {
  waiting: "Waiting for a transcription",
  converting: "Preparing audio",
  diarizing: "Identifying speakers",
  loading: "Loading model",
  listening: "Listening",
  transcribing: "Transcribing",
  finished: "Finished",
  error: "Failed",
  canceled: "Canceled",
};

export function phaseLabel(run: RunState | null, phase: DisplayPhase): string {
  if (phase === "diarizing" && run?.progress?.detail === "segmentation") return "Segmenting";
  if (phase === "diarizing" && run?.progress?.detail === "embeddings") return "Comparing voices";
  if (phase === "error" && run?.stale && !run.endStatus) return "Stopped unexpectedly";
  return PHASE_LABEL[phase];
}

export function isRunActive(run: RunState | null): boolean {
  return !!run && !run.endStatus && !run.stale;
}

/** Per-segment latency: arrival on this page minus the CLI write time. */
export function segmentLatencyMs(seg: Segment): number {
  return seg.recvAt - seg.t * 1000;
}

export interface LatencyStats {
  last: number | null;
  median: number | null;
  tail: number | null;
  push: number | null;
}

export function latencyStats(run: RunState | null): LatencyStats {
  const live = run ? run.segments.filter((s) => s.live) : [];
  if (live.length === 0) return { last: null, median: null, tail: null, push: null };
  const values = live.map(segmentLatencyMs).sort((a, b) => a - b);
  const mid = Math.floor(values.length / 2);
  const median = values.length % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
  const lastSeg = live[live.length - 1];
  const haveServer = lastSeg.serverT !== null;
  return {
    last: segmentLatencyMs(lastSeg),
    median,
    tail: haveServer ? (lastSeg.serverT! - lastSeg.t) * 1000 : null,
    push: haveServer ? lastSeg.recvAt - lastSeg.serverT! * 1000 : null,
  };
}

/**
 * When a run stopped, in unix seconds: the run_end time (or the summary's ended_t) for an
 * ended run, the server's inferred end (else the last event) for a stale one. Null while running.
 */
export function stoppedT(run: RunState): number | null {
  if (run.endStatus) return run.endedT ?? run.lastT ?? run.startedT;
  if (run.stale) return run.inferredEndT ?? run.lastT ?? run.startedT;
  return null;
}

/** Elapsed run time in seconds; frozen once the run has ended or stopped. */
export function elapsedSeconds(run: RunState | null, nowMs: number): number | null {
  if (!run || run.startedT === null) return null;
  const end = stoppedT(run) ?? nowMs / 1000;
  return Math.max(0, end - run.startedT);
}

/** Real-time factor: processing time / audio time. Lower is faster. */
export function realTimeFactor(run: RunState | null, nowMs: number): number | null {
  if (!run || run.startedT === null) return null;
  if (run.endStatus) {
    return run.elapsed !== null && run.duration ? run.elapsed / run.duration : null;
  }
  const last = run.segments[run.segments.length - 1];
  if (!last) return null;
  const audio = Math.max(0.001, last.end - run.startOffset);
  const end = stoppedT(run) ?? nowMs / 1000;
  return (end - run.startedT) / audio;
}

/** Media seconds transcribed so far (end of the last segment). */
export function frontier(run: RunState | null): number | null {
  if (!run || run.segments.length === 0) return null;
  return run.segments[run.segments.length - 1].end;
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** 0..1 progress: media position during transcription, the CLI's pct otherwise. */
export function progressFraction(run: RunState | null): number {
  if (!run) return 0;
  if (run.endStatus === "finished") return 1;
  const end = frontier(run);
  if (end !== null && run.duration && run.duration > 0) {
    return clamp01((end - run.startOffset) / run.duration);
  }
  return run.progress ? clamp01(run.progress.pct / 100) : 0;
}
