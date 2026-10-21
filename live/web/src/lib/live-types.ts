// Wire types for the live feed. They mirror the NDJSON written by the CLI
// (noScribe/live_feed.py) and the SSE payloads served at /api/stream.

export type RunStatus = "running" | "finished" | "error" | "canceled" | "stale";

export interface RunSummary {
  run_id: string;
  audio_name: string;
  model: string | null;
  language: string | null;
  status: RunStatus;
  started_t: number | null;
  ended_t: number | null;
  last_t: number | null;
  segments: number;
  duration: number | null;
  device: string | null;
  device_name: string | null;
  feed_file: string | null;
  /** status === "running". Optional until the server sends it. */
  live?: boolean;
  /** Last event time for a stale run, ended_t for an ended run, null while running. */
  inferred_end_t?: number | null;
  /** Basename of the output HTML, only when that file exists. */
  output_name?: string | null;
  /** The language the CLI detected (from its language event); null until then. `language` above is the configured setting ("Auto" or a fixed code). */
  detected_language?: string | null;
}

interface EventBase {
  v: number;
  /** Unix seconds, written by the CLI. */
  t: number;
  seq: number;
  run_id: string;
  /** Unix seconds when the server read the line. */
  server_t?: number;
}

export interface RunStartEvent extends EventBase {
  type: "run_start";
  audio_file: string;
  output_file: string | null;
  model: string | null;
  language: string | null;
  speaker_detection: string | null;
  options: { overlapping: boolean; timestamps: boolean; disfluencies: boolean; pause: unknown };
  pid: number;
  noscribe_version: string | null;
}

export interface PhaseEvent extends EventBase {
  type: "phase";
  phase: string;
}

export interface ProgressEvent extends EventBase {
  type: "progress";
  phase: string;
  pct: number;
  detail: string | null;
}

export interface AudioEvent extends EventBase {
  type: "audio";
  duration: number;
  start_offset: number;
}

export interface DiarizationEvent extends EventBase {
  type: "diarization";
  speakers: string[];
  turns: number;
}

export interface ModelReadyEvent extends EventBase {
  type: "model_ready";
  component: string;
  device: string | null;
  device_name: string | null;
  compute_type: string | null;
  load_seconds: number | null;
}

export interface LanguageEvent extends EventBase {
  type: "language";
  language: string | null;
  probability: number | null;
}

export type LogLevel = "debug" | "info" | "warning" | "error";

/** A line of CLI output. `replace` marks a carriage-return progress update of the previous line from the same source. */
export interface LogEvent extends EventBase {
  type: "log";
  level: LogLevel;
  source: string;
  msg: string;
  replace?: boolean;
}

export interface SegmentEvent extends EventBase {
  type: "segment";
  index: number;
  /** Absolute media seconds. */
  start: number;
  end: number;
  /** "S00", "//S01" (overlapping speech) or "" (no speaker). */
  speaker: string;
  /** Raw text, may carry a leading space. */
  text: string;
}

export interface RunEndEvent extends EventBase {
  type: "run_end";
  status: "finished" | "error" | "canceled";
  error: string | null;
  output_file: string | null;
  elapsed: number | null;
}

export type FeedEvent =
  | RunStartEvent
  | PhaseEvent
  | ProgressEvent
  | AudioEvent
  | DiarizationEvent
  | ModelReadyEvent
  | LanguageEvent
  | LogEvent
  | SegmentEvent
  | RunEndEvent;

export interface HelloPayload {
  server_t: number;
  runs: RunSummary[];
}

export interface SnapshotPayload {
  run_id: string | null;
  summary: RunSummary | null;
  events: FeedEvent[];
}

export interface FeedPayload {
  run_id: string;
  event: FeedEvent;
}

export interface RunsPayload {
  runs: RunSummary[];
}

export interface PeaksPayload {
  run_id: string;
  duration: number;
  n: number;
  peaks: number[];
}
