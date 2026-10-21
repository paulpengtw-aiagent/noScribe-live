import { useSyncExternalStore } from "react";
import type { RunCorrections } from "@/lib/llm/types";

// AI correction results in IndexedDB: one row per transcript run, keyed by runId. Plain IndexedDB, no library.
// The database name is shared with other features, so it is opened without a version, and the object store is
// added with a version bump only when it is missing.

const DB_NAME = "noscribe-live";
const STORE = "corrections";

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(version?: number): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = version === undefined ? indexedDB.open(DB_NAME) : indexedDB.open(DB_NAME, version);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: "runId" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB is unavailable"));
  });
}

function db(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const first = await openDb();
      if (first.objectStoreNames.contains(STORE)) return first;
      const next = first.version + 1;
      first.close();
      return openDb(next);
    })().catch((err: unknown) => {
      dbPromise = null;
      throw err;
    });
  }
  return dbPromise;
}

function request<T>(mode: IDBTransactionMode, make: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return db().then(
    (database) =>
      new Promise<T>((resolve, reject) => {
        const tx = database.transaction(STORE, mode);
        const req = make(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(req.result);
        tx.onerror = () => reject(tx.error ?? req.error);
        tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
      }),
  );
}

// Change notification for the transcript card and the panel. Every save, delete and view change bumps the version.
const listeners = new Set<() => void>();
let version = 0;

function emit(): void {
  version++;
  for (const fn of listeners) fn();
}

/** Calls `listener` after any save, delete or view change. Returns the unsubscribe function. */
export function subscribeCorrections(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** A number that changes whenever the stored corrections or the view flags change. */
export function correctionsVersion(): number {
  return version;
}

export async function loadCorrections(runId: string): Promise<RunCorrections | null> {
  const row = await request<RunCorrections | undefined>("readonly", (store) => store.get(runId));
  return row ?? null;
}

export async function saveCorrections(rc: RunCorrections): Promise<void> {
  await request("readwrite", (store) => store.put(rc));
  emit();
}

export async function deleteCorrections(runId: string): Promise<void> {
  await request("readwrite", (store) => store.delete(runId));
  emit();
}

// The "show original" view flag. Session only: it is not persisted.
const showingOriginal = new Set<string>();

export function isShowingOriginal(runId: string): boolean {
  return showingOriginal.has(runId);
}

export function setShowingOriginal(runId: string, on: boolean): void {
  if (on) showingOriginal.add(runId);
  else showingOriginal.delete(runId);
  emit();
}

/** React hook: whether the transcript shows the original text for this run. */
export function useShowingOriginal(runId: string): boolean {
  return useSyncExternalStore(subscribeCorrections, () => showingOriginal.has(runId));
}

/** The accepted corrected text by segment index. Empty when nothing is accepted. */
export function acceptedTexts(rc: RunCorrections | null): Map<number, string> {
  const out = new Map<number, string>();
  for (const item of rc?.items ?? []) {
    if (item.status === "accepted") out.set(item.segmentIndex, item.corrected);
  }
  return out;
}
