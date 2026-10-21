import { useMemo, useSyncExternalStore } from "react";
import type { ContextDoc } from "./types";
import { docKind, parseFile } from "./parse-docs";

/** Limits on the attached reference documents, applied when files are added. */
export const CONTEXT_LIMITS = { maxFiles: 30, maxTotalBytes: 50 * 1024 * 1024 } as const;

/**
 * Error messages for files the store refuses to accept. They are stored in `ContextDoc.error`, and the
 * panel matches on them to show a localised message. Refused rows do not count toward the limits.
 */
export const CONTEXT_REJECT = {
  tooManyFiles: "Too many files",
  tooLarge: "Files are too large in total",
  unsupported: "Unsupported file type",
} as const;

export interface ContextDocsState {
  docs: ContextDoc[];
  freeText: string;
}

export interface ContextDocsApi extends ContextDocsState {
  /** Adds files and parses them one at a time. Files over a limit are added as "error" rows. */
  addFiles(files: File[]): void;
  /** Removes a row. Parsing of that file is cancelled. */
  remove(id: string): void;
  setFreeText(text: string): void;
  /** Removes all documents and cancels parsing. The free text is kept. */
  clear(): void;
}

// Module state, so the context lives in this tab only and is not persisted.
let state: ContextDocsState = { docs: [], freeText: "" };
const listeners = new Set<() => void>();
/** Files waiting to be parsed, by doc id. Released once parsing ends. */
const pendingFiles = new Map<string, File>();
/** Abort controller of the file being parsed, by doc id. */
const inFlight = new Map<string, AbortController>();
/** Ids of rows refused when added. They do not count toward the limits. */
const refused = new Set<string>();
let pumping = false;
let seq = 0;

function emit(next: ContextDocsState): void {
  state = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function nextId(): string {
  seq += 1;
  return `ctx-${Date.now().toString(36)}-${seq}`;
}

function patch(id: string, change: Partial<ContextDoc>): void {
  if (!state.docs.some((d) => d.id === id)) return;
  emit({ ...state, docs: state.docs.map((d) => (d.id === id ? { ...d, ...change } : d)) });
}

/** Parses queued documents one at a time until none are left. */
async function pump(): Promise<void> {
  if (pumping) return;
  pumping = true;
  try {
    for (;;) {
      const next = state.docs.find((d) => d.status === "queued");
      if (!next) break;
      const id = next.id;
      const file = pendingFiles.get(id);
      if (!file) {
        patch(id, { status: "error", error: "The file is no longer available." });
        continue;
      }
      patch(id, { status: "parsing" });
      const controller = new AbortController();
      inFlight.set(id, controller);
      try {
        const text = await parseFile(file, controller.signal);
        patch(id, { status: "ok", text, chars: text.length, error: undefined });
      } catch (err) {
        // A removed or cleared row is already gone; patch() ignores it.
        if (!controller.signal.aborted) {
          patch(id, { status: "error", error: err instanceof Error ? err.message : String(err) });
        }
      } finally {
        inFlight.delete(id);
        pendingFiles.delete(id);
      }
    }
  } finally {
    pumping = false;
  }
}

function addFiles(incoming: File[]): void {
  let counted = 0;
  let bytes = 0;
  for (const d of state.docs) {
    if (!refused.has(d.id)) {
      counted += 1;
      bytes += d.bytes;
    }
  }

  const added: ContextDoc[] = [];
  for (const file of incoming) {
    const id = nextId();
    const kind = docKind(file.name);
    let refusal: string | null = null;
    if (!kind) refusal = CONTEXT_REJECT.unsupported;
    else if (counted >= CONTEXT_LIMITS.maxFiles) refusal = CONTEXT_REJECT.tooManyFiles;
    else if (bytes + file.size > CONTEXT_LIMITS.maxTotalBytes) refusal = CONTEXT_REJECT.tooLarge;

    if (refusal !== null || !kind) {
      refused.add(id);
      added.push({ id, name: file.name, kind: kind ?? "text", bytes: file.size, status: "error", error: refusal ?? undefined });
      continue;
    }
    counted += 1;
    bytes += file.size;
    pendingFiles.set(id, file);
    added.push({ id, name: file.name, kind, bytes: file.size, status: "queued" });
  }

  if (added.length > 0) emit({ ...state, docs: [...state.docs, ...added] });
  void pump();
}

function remove(id: string): void {
  inFlight.get(id)?.abort();
  inFlight.delete(id);
  pendingFiles.delete(id);
  refused.delete(id);
  if (!state.docs.some((d) => d.id === id)) return;
  emit({ ...state, docs: state.docs.filter((d) => d.id !== id) });
}

function setFreeText(text: string): void {
  if (text === state.freeText) return;
  emit({ ...state, freeText: text });
}

function clear(): void {
  for (const controller of inFlight.values()) controller.abort();
  inFlight.clear();
  pendingFiles.clear();
  refused.clear();
  emit({ ...state, docs: [] });
}

/** Current documents and free text, for code outside React. Treat the returned value as read-only. */
export function getContextDocs(): ContextDocsState {
  return state;
}

/** Shared, per-tab context documents and free text. Actions are stable across renders. */
export function useContextDocs(): ContextDocsApi {
  const snapshot = useSyncExternalStore(subscribe, getContextDocs);
  return useMemo(
    () => ({ docs: snapshot.docs, freeText: snapshot.freeText, addFiles, remove, setFreeText, clear }),
    [snapshot],
  );
}
