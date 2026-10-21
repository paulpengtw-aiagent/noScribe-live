import { useCallback, useSyncExternalStore } from "react";
import { isCjkChar } from "@/lib/format";

type Convert = (text: string) => string;

// The converter comes from its own chunk (opencc-js/cn2t), so the main bundle does not carry the dictionary.
// Loading and building it is one synchronous burst on the main thread (about 100 ms in the headless replay). Two
// triggers start it: an idle preload when a transcript mounts, and an immediate request as soon as CJK text is seen
// (requestConverter), which does not wait for idle. The flip notifies the subscribed transcripts at once, after the
// build (useSyncExternalStore). Until the converter is ready, the transcript holds CJK text back; after ZH_FALLBACK_MS
// (in transcript-card) it draws the raw text instead, and the converted text replaces it when the flip arrives.
let convert: Convert | null = null;
let loading = false;
let scheduled = false;
let wanted = false;
const listeners = new Set<() => void>();

/** Test instrumentation, exposed as window.__nsliveZh. heldSegments counts the segments the transcript holds for the converter. */
export interface ZhStats {
  ready: boolean;
  heldSegments: number;
}

export const zhStats: ZhStats = { ready: false, heldSegments: 0 };

declare global {
  interface Window {
    __nsliveZh?: ZhStats;
    /** Test only: holds the converter back this many ms after its import resolves. Unset or 0 means no delay. */
    __NSLIVE_ZH_DELAY_MS?: number;
  }
}

if (typeof window !== "undefined") window.__nsliveZh = zhStats;

function testDelayMs(): number {
  const delay = typeof window !== "undefined" ? window.__NSLIVE_ZH_DELAY_MS : undefined;
  return typeof delay === "number" && delay > 0 ? delay : 0;
}

// Safari has no requestIdleCallback, so a timer stands in. The timeout lets the load run even while a run keeps the page busy.
const IDLE_TIMEOUT_MS = 1500;
const FALLBACK_DELAY_MS = 800;
// A failed import is retried only while CJK text is waiting for the converter.
const RETRY_MS = 3000;

function whenIdle(task: () => void): void {
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(() => task(), { timeout: IDLE_TIMEOUT_MS });
  } else {
    window.setTimeout(task, FALLBACK_DELAY_MS);
  }
}

function load(): void {
  if (convert || loading) return;
  loading = true;
  performance.mark("zh-tw:import-start");
  import("opencc-js/cn2t")
    .then((mod) => {
      const ready = () => {
        convert = mod.Converter({ from: "cn", to: "tw" });
        zhStats.ready = true;
        performance.mark("zh-tw:converter-ready");
        // Synchronous: the flip is seen by every subscriber now. A subscriber that registers later reads `convert` in
        // getSnapshot (useSyncExternalStore also re-checks the snapshot when it subscribes), so no flip is missed.
        listeners.forEach((notify) => notify());
      };
      const delay = testDelayMs();
      if (delay > 0) window.setTimeout(ready, delay);
      else ready();
    })
    .catch(() => {
      // The CJK text stays held back; a waiting request retries the import.
      loading = false;
      if (wanted && !convert) window.setTimeout(load, RETRY_MS);
    });
}

/** Starts the converter now, for CJK text that is waiting on it. Safe to call again. */
export function requestConverter(): void {
  wanted = true;
  load();
}

// Two frames put the request after the first paint; the idle callback then keeps the preload off busy frames.
function scheduleLoad(): void {
  if (convert || loading || scheduled) return;
  scheduled = true;
  requestAnimationFrame(() =>
    requestAnimationFrame(() =>
      whenIdle(() => {
        scheduled = false;
        load();
      }),
    ),
  );
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  scheduleLoad();
  return () => {
    listeners.delete(notify);
  };
}

function snapshot(): Convert | null {
  return convert;
}

// Every render converts each segment again, so results are kept per raw text (one converter at a time).
const CACHE_LIMIT = 4000;
let cache = new Map<string, string>();
let cacheOwner: Convert | null = null;

/** True when the text has a CJK character: the text the converter changes, and the text held back until it is ready. */
export function hasCJK(text: string): boolean {
  for (const ch of text) if (isCjkChar(ch)) return true;
  return false;
}

/**
 * Display-only Simplified to Traditional (Taiwan). The raw text is returned when no converter is loaded yet,
 * when the text has no CJK, or when the conversion changes its length: the streaming reveal counts characters.
 */
export function toTraditionalTw(text: string, converter: Convert | null): string {
  if (!converter || !hasCJK(text)) return text;
  if (cacheOwner !== converter) {
    cache.clear();
    cacheOwner = converter;
  }
  const known = cache.get(text);
  if (known !== undefined) return known;
  const out = converter(text);
  const result = out.length === text.length ? out : text;
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(text, result);
  return result;
}

export interface ZhConverter {
  /** Display conversion. Returns the raw text until the converter is ready. */
  display: (text: string) => string;
  /** True once the converter is loaded. Until then, CJK text must not be painted. */
  ready: boolean;
}

/** The display converter and whether it is ready. The user re-renders once the dictionary has loaded. */
export function useZhConverter(): ZhConverter {
  const converter = useSyncExternalStore(subscribe, snapshot, snapshot);
  const display = useCallback((text: string) => toTraditionalTw(text, converter), [converter]);
  return { display, ready: converter !== null };
}

/** A display converter. Its user re-renders once the dictionary has loaded. */
export function useZhTw(): (text: string) => string {
  return useZhConverter().display;
}
