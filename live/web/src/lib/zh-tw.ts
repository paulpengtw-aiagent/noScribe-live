import { useCallback, useSyncExternalStore } from "react";
import { isCjkChar } from "@/lib/format";

type Convert = (text: string) => string;

// The converter comes from its own chunk (opencc-js/cn2t) and is loaded on first subscribe, so the main bundle
// does not carry the dictionary. Until it arrives, text is shown as the backend wrote it.
let convert: Convert | null = null;
let loading = false;
const listeners = new Set<() => void>();

function load(): void {
  if (convert || loading) return;
  loading = true;
  import("opencc-js/cn2t")
    .then((mod) => {
      convert = mod.Converter({ from: "cn", to: "tw" });
      listeners.forEach((notify) => notify());
    })
    .catch(() => {
      // The raw text stays on screen; the next subscriber tries the import again.
      loading = false;
    });
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  load();
  return () => {
    listeners.delete(notify);
  };
}

function snapshot(): Convert | null {
  return convert;
}

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
  const out = converter(text);
  return out.length === text.length ? out : text;
}

/** A display converter. Its user re-renders once the dictionary has loaded. */
export function useZhTw(): (text: string) => string {
  const converter = useSyncExternalStore(subscribe, snapshot, snapshot);
  return useCallback((text: string) => toTraditionalTw(text, converter), [converter]);
}
