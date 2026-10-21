import { chatCompletion } from "@/lib/llm/client";
import { buildContext } from "@/lib/llm/retrieval";
import type { ContextDoc, Correction, LlmError, LlmSettings, SegmentRef } from "@/lib/llm/types";

/** Segments sent per request. */
const BATCH_SIZE = 20;
/** Read-only neighbours sent before and after each batch, so the model sees the sentences around it. */
const NEIGHBOURS = 2;
/** Token budget for the reference material added to each request. */
const CONTEXT_TOKENS = 6000;

const SYSTEM_PROMPT = [
  "You correct machine-generated transcripts of speech. The text may be Chinese, English, or both.",
  "Make only faithful corrections: fix misrecognised names, technical terms and homophones, and punctuation.",
  "Use the reference material, when given, to decide the right spelling of names and terms.",
  "Never add, remove, summarise or invent content. Keep the meaning and the length of the speech as it is.",
  "Write Chinese text in Traditional Chinese (Taiwan) characters.",
  "Segments marked as read-only context are for understanding only; never return them.",
  "Reply ONLY with a JSON array, with no prose and no code fence. Each item is",
  '{"segment_id": <the number after # in [#...]>, "corrected": "<the whole corrected segment text>", "reason": "<short reason>"}.',
  "List only the segments you changed. If nothing needs changing, reply with [].",
].join("\n");

const REPAIR_INSTRUCTION =
  "Your previous reply was not a valid JSON array. Reply again with ONLY the JSON array described in the instructions: no prose, no code fence.";

/** One message in the chat request. */
interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface RunCorrectionsOptions {
  /** Id of the transcript run the segments belong to. */
  runId: string;
  segments: SegmentRef[];
  settings: LlmSettings;
  apiKey: string;
  docs: ContextDoc[];
  freeText: string;
  signal?: AbortSignal;
  /** Called with the batches finished so far and the total batch count. */
  onProgress?: (done: number, total: number) => void;
}

/**
 * Runs the correction model over every segment and returns the proposed changes, all with status "pending".
 * Unchanged segments are dropped. Throws LlmError: "aborted" when the signal fires, "json" when a batch still
 * has no usable reply after one repair retry, and whatever kind chatCompletion throws otherwise.
 */
export async function runCorrections(options: RunCorrectionsOptions): Promise<Correction[]> {
  const { segments, signal, onProgress } = options;
  const ordered = [...segments].sort((a, b) => a.index - b.index);
  const order = speakerOrder(ordered);
  const total = Math.ceil(ordered.length / BATCH_SIZE);
  onProgress?.(0, total);
  const out: Correction[] = [];
  for (let b = 0; b < total; b++) {
    throwIfAborted(signal);
    const start = b * BATCH_SIZE;
    const batch = ordered.slice(start, start + BATCH_SIZE);
    const before = ordered.slice(Math.max(0, start - NEIGHBOURS), start);
    const after = ordered.slice(start + BATCH_SIZE, start + BATCH_SIZE + NEIGHBOURS);
    const items = await correctBatch(options, batch, [...before, ...after], order);
    out.push(...items);
    onProgress?.(b + 1, total);
  }
  return out;
}

async function correctBatch(
  options: RunCorrectionsOptions,
  batch: SegmentRef[],
  context: SegmentRef[],
  order: Map<string, number>,
): Promise<Correction[]> {
  const { settings, apiKey, docs, freeText, signal } = options;
  const batchLines = batch.map((s) => lineFor(s, order)).join("\n");
  const ref = buildContext(docs, freeText, batchLines, CONTEXT_TOKENS);
  const sections = [
    ref.text ? `Reference material:\n${ref.text}` : "",
    context.length > 0
      ? `Read-only context (do not return these):\n${context.map((s) => lineFor(s, order)).join("\n")}`
      : "",
    `Segments to correct:\n${batchLines}`,
  ];
  const messages: ChatMessage[] = [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: sections.filter((s) => s !== "").join("\n\n") },
  ];
  const send = (): Promise<string> => chatCompletion({ settings, apiKey, messages, signal, json: false });

  let reply = await send();
  let items = parseReply(reply);
  if (items === null) {
    // One retry: show the model its own reply and ask for a valid array only.
    messages.push({ role: "assistant", content: reply }, { role: "user", content: REPAIR_INSTRUCTION });
    reply = await send();
    items = parseReply(reply);
    if (items === null) {
      const err: LlmError = { kind: "json", message: "The model reply was not a JSON array after one retry." };
      throw err;
    }
  }
  return toCorrections(items, batch);
}

/** The reply as a JSON array: the whole text when it parses, else the first balanced [...] in it. Null otherwise. */
function parseReply(raw: string): unknown[] | null {
  const text = raw.replace(/```(?:json)?/gi, "").trim();
  for (const candidate of [text, firstArray(text)]) {
    if (!candidate) continue;
    try {
      const value: unknown = JSON.parse(candidate);
      if (Array.isArray(value)) return value;
    } catch {
      // Not JSON: try the next candidate.
    }
  }
  return null;
}

/** The first balanced [...] in the text, skipping brackets inside JSON strings. */
function firstArray(text: string): string | null {
  const start = text.indexOf("[");
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
    } else if (ch === '"') {
      inString = true;
    } else if (ch === "[") {
      depth++;
    } else if (ch === "]") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

/** Keeps valid, changed items for segments of this batch. Each segment appears at most once. */
function toCorrections(items: unknown[], batch: SegmentRef[]): Correction[] {
  const byIndex = new Map(batch.map((s) => [s.index, s] as const));
  const seen = new Set<number>();
  const out: Correction[] = [];
  for (const item of items) {
    if (typeof item !== "object" || item === null) continue;
    const { segment_id, corrected, reason } = item as Record<string, unknown>;
    const id = typeof segment_id === "string" && /^\d+$/.test(segment_id) ? Number(segment_id) : segment_id;
    if (typeof id !== "number" || !Number.isInteger(id)) continue;
    const seg = byIndex.get(id);
    if (!seg || seen.has(id) || typeof corrected !== "string") continue;
    const text = corrected.trim();
    if (text === "") continue;
    seen.add(id);
    if (text === seg.text.trim()) continue;
    out.push({
      segmentIndex: id,
      original: seg.text,
      corrected: text,
      reason: typeof reason === "string" ? reason.trim() : "",
      status: "pending",
    });
  }
  return out;
}

const NUMBERED_SPEAKER = /^S\d+$/;

function speakerKey(label: string): string {
  return label.startsWith("//") ? label.slice(2) : label;
}

/** Numbers the speakers by first appearance, as the transcript does, so the model reads "Speaker 1", "Speaker 2". */
function speakerOrder(segments: SegmentRef[]): Map<string, number> {
  const order = new Map<string, number>();
  for (const s of segments) {
    if (!s.speaker) continue;
    const key = speakerKey(s.speaker);
    if (!order.has(key)) order.set(key, order.size + 1);
  }
  return order;
}

function speakerName(label: string, order: Map<string, number>): string {
  const key = speakerKey(label);
  const n = order.get(key);
  return NUMBERED_SPEAKER.test(key) && n !== undefined ? `Speaker ${n}` : key;
}

function clock(seconds: number): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** One prompt line: `[#index] [m:ss] Speaker n: text`. The speaker part is omitted when the segment has none. */
function lineFor(s: SegmentRef, order: Map<string, number>): string {
  const who = s.speaker ? `${speakerName(s.speaker, order)}: ` : "";
  return `[#${s.index}] [${clock(s.start)}] ${who}${s.text.replace(/\s+/g, " ").trim()}`;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    const err: LlmError = { kind: "aborted", message: "Correction was cancelled." };
    throw err;
  }
}
