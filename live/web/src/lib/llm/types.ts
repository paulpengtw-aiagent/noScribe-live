// Shared contracts for the LLM correction feature (frontend only).
// Feature agents import these types from here. This module must stay free of runtime
// imports: the document parsers (mammoth, pdfjs-dist, fflate, diff) are loaded lazily
// by the feature code with dynamic import() and must never be imported from this file.

/** Connection settings for a chat endpoint. The API key is not part of this type; it is handled separately. */
export interface LlmSettings {
  /** Base URL of the chat endpoint. */
  baseUrl: string;
  model: string;
  /** Sampling temperature. Omitted means the server default. */
  temperature?: number;
  /** Whether to keep these settings across page reloads. */
  remember: boolean;
}

/** A reference document the user attaches as context. The extracted plain text is in `text` once status is "ok". */
export interface ContextDoc {
  id: string;
  name: string;
  kind: "docx" | "pdf" | "text";
  /** Size of the uploaded file in bytes. */
  bytes: number;
  status: "queued" | "parsing" | "ok" | "error";
  /** Extracted plain text, present when status is "ok". */
  text?: string;
  /** Human-readable parse failure, present when status is "error". */
  error?: string;
  /** Character count of `text`, for budget display. */
  chars?: number;
}

/** A transcript segment as the correction feature sees it. */
export interface SegmentRef {
  /** Position of the segment in the run; `Correction.segmentIndex` refers to this value. */
  index: number;
  /** Sequence number from the live event stream, when known. */
  seq?: number;
  /** Speaker label, or null when the segment has no speaker. The live feed sends "" for no speaker; map that to null. */
  speaker: string | null;
  /** Absolute media start time in seconds. */
  start: number;
  /** Absolute media end time in seconds. */
  end: number;
  /** Display text in Traditional Chinese, trimmed, as the transcript view shows it. */
  text: string;
}

/** One proposed edit to a single segment. `original` is the text the model was given; `corrected` is its proposal. */
export interface Correction {
  segmentIndex: number;
  original: string;
  corrected: string;
  /** The model's justification, shown to the reviewer. */
  reason: string;
  status: "pending" | "accepted" | "rejected";
}

/** The stored result of one correction run over the segments of a transcript run. */
export interface RunCorrections {
  /** Id of the transcript run whose segments were corrected. */
  runId: string;
  /** Model that produced `items`. */
  model: string;
  /** Creation time in Unix seconds, the same unit as the live feed's `t` (not milliseconds). */
  createdAt: number;
  items: Correction[];
  /** Optional free-text note from the model or the pipeline. */
  note?: string;
}

/**
 * Failure classes for a call to the chat endpoint, so the UI can say what to fix. "auth" is 401, "forbidden" is 403,
 * "rate_limit" is 429, "overloaded" is 529, and "http" is any other non-2xx reply.
 */
export type LlmErrorKind =
  | "cors"
  | "network"
  | "http"
  | "auth"
  | "forbidden"
  | "rate_limit"
  | "overloaded"
  | "json"
  | "aborted";

/** A failed call to the chat endpoint. */
export interface LlmError {
  kind: LlmErrorKind;
  message: string;
  /** HTTP status code, when the failure came with one. */
  status?: number;
}

// CJK ideographs, kana, hangul and bopomofo. These carry more meaning per character than Latin text.
const CJK_CHAR = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Script=Bopomofo}]/gu;

/**
 * Rough token count for budgeting how much context fits in a request. It is not a tokenizer.
 * Non-CJK text is counted at 4 characters per token and CJK characters at 1.5 characters per
 * token (so each CJK character costs about 2/3 of a token). Counts code points, so an astral
 * character counts once. The result is rounded up, and an empty string gives 0.
 */
export function estimateTokens(text: string): number {
  if (text.length === 0) return 0;
  const cjk = text.match(CJK_CHAR)?.length ?? 0;
  const other = Array.from(text).length - cjk;
  return Math.ceil(other / 4 + cjk / 1.5);
}
