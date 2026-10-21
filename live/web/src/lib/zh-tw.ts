import { useCallback, useSyncExternalStore } from "react";
import { isCjkChar } from "@/lib/format";

type Convert = (text: string) => string;

// The converter comes from its own chunk (opencc-js/cn2t), so the main bundle does not carry the dictionary.
// Loading and building it is one synchronous burst on the main thread (about 100 ms in the headless replay), so it
// starts after the first paint and in an idle period, not on the first streamed frames. The notify that re-renders
// the transcript runs in a task of its own, after the build. Until the converter is ready, text is shown as the
// backend wrote it.
let convert: Convert | null = null;
let loading = false;
let scheduled = false;
const listeners = new Set<() => void>();

// Safari has no requestIdleCallback, so a timer stands in. The timeout lets the load run even while a run keeps the page busy.
const IDLE_TIMEOUT_MS = 1500;
const FALLBACK_DELAY_MS = 800;

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
      convert = mod.Converter({ from: "cn", to: "tw" });
      performance.mark("zh-tw:converter-ready");
      window.setTimeout(() => listeners.forEach((notify) => notify()), 0);
    })
    .catch(() => {
      // The raw text stays on screen; the next subscriber tries the import again.
      loading = false;
    });
}

// Two frames put the request after the first paint; the idle callback then keeps the load off busy frames.
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

function hasCjk(text: string): boolean {
  for (const ch of text) if (isCjkChar(ch)) return true;
  return false;
}

/**
 * Display-only Simplified to Traditional (Taiwan). The raw text is returned when no converter is loaded yet,
 * when the text has no CJK, or when the conversion changes its length: the streaming reveal counts characters.
 */
export function toTraditionalTw(text: string, converter: Convert | null): string {
  if (!converter || !hasCjk(text)) return text;
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

/** A display converter. Its user re-renders once the dictionary has loaded. */
export function useZhTw(): (text: string) => string {
  const converter = useSyncExternalStore(subscribe, snapshot, snapshot);
  return useCallback((text: string) => toTraditionalTw(text, converter), [converter]);
}
