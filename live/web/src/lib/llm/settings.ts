// Connection settings for the LLM correction feature. Non-secret settings live in localStorage. The API key lives in
// sessionStorage, and also in localStorage only when the user chose "remember on this browser". The key is never logged.
import { useMemo, useSyncExternalStore } from "react";
import { ANTHROPIC_DEFAULT_MODEL } from "./anthropic";
import type { LlmSettings } from "./types";

/** localStorage key for the non-secret settings (base URL, model, temperature, remember). */
export const LLM_SETTINGS_KEY = "noscribe-live-llm-settings";
/** Storage key for the API key: sessionStorage always, localStorage only when `remember` is true. */
export const LLM_KEY_STORAGE = "noscribe-live-llm-key";

export const DEFAULT_LLM_MODEL = ANTHROPIC_DEFAULT_MODEL;

export interface LlmSettingsApi {
  settings: LlmSettings;
  apiKey: string;
  /** Stores the settings and the key. The key goes to sessionStorage, and to localStorage only when `next.remember` is true. */
  save(next: LlmSettings, apiKey: string): void;
  /** Forgets the API key in both storages and turns `remember` off. The other settings are kept. */
  clear(): void;
}

interface State {
  settings: LlmSettings;
  apiKey: string;
}

/** Coerces stored or caller-supplied values into a valid LlmSettings. Anything malformed falls back to the default. */
function sanitize(value: unknown): LlmSettings {
  const v: Record<string, unknown> = typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  const model = typeof v.model === "string" ? v.model.trim() : "";
  const temperature =
    typeof v.temperature === "number" && Number.isFinite(v.temperature) && v.temperature >= 0 && v.temperature <= 2
      ? v.temperature
      : undefined;
  return {
    baseUrl: typeof v.baseUrl === "string" ? v.baseUrl.trim() : "",
    model: model || DEFAULT_LLM_MODEL,
    temperature,
    remember: v.remember === true,
  };
}

function readSettings(): LlmSettings {
  try {
    const raw = window.localStorage.getItem(LLM_SETTINGS_KEY);
    return sanitize(raw === null ? null : JSON.parse(raw));
  } catch {
    // Storage is unavailable or the saved JSON is corrupt: use the defaults.
    return sanitize(null);
  }
}

function readKey(remember: boolean): string {
  try {
    const fromSession = window.sessionStorage.getItem(LLM_KEY_STORAGE);
    if (fromSession) return fromSession;
  } catch {
    // Storage is unavailable; fall through.
  }
  if (remember) {
    try {
      return window.localStorage.getItem(LLM_KEY_STORAGE) ?? "";
    } catch {
      // Storage is unavailable.
    }
  }
  return "";
}

// The state is read on first use, not at import, so importing this module never touches storage.
let state: State | null = null;

function current(): State {
  if (state === null) {
    const settings = readSettings();
    state = { settings, apiKey: readKey(settings.remember) };
  }
  return state;
}

const listeners = new Set<() => void>();

function setState(next: State): void {
  state = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function writeSettings(settings: LlmSettings): void {
  try {
    window.localStorage.setItem(LLM_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Storage is unavailable: the settings still apply for this page view.
  }
}

function writeKey(key: string, remember: boolean): void {
  try {
    if (key) window.sessionStorage.setItem(LLM_KEY_STORAGE, key);
    else window.sessionStorage.removeItem(LLM_KEY_STORAGE);
  } catch {
    // Storage is unavailable: the key still applies for this page view.
  }
  try {
    if (remember && key) window.localStorage.setItem(LLM_KEY_STORAGE, key);
    else window.localStorage.removeItem(LLM_KEY_STORAGE);
  } catch {
    // Storage is unavailable.
  }
}

function save(next: LlmSettings, apiKey: string): void {
  const settings = sanitize(next);
  const key = apiKey.trim();
  writeSettings(settings);
  writeKey(key, settings.remember);
  setState({ settings, apiKey: key });
}

function clear(): void {
  const settings: LlmSettings = { ...current().settings, remember: false };
  writeSettings(settings);
  writeKey("", false);
  setState({ settings, apiKey: "" });
}

/** The shared LLM settings: `{ settings, apiKey, save(next, apiKey), clear() }`. Every mounted user re-renders on save or clear. */
export function useLlmSettings(): LlmSettingsApi {
  const snapshot = useSyncExternalStore(subscribe, current, current);
  return useMemo(
    () => ({ settings: snapshot.settings, apiKey: snapshot.apiKey, save, clear }),
    [snapshot],
  );
}

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

function isLocalIpv4(host: string): boolean {
  const match = IPV4.exec(host);
  if (!match) return false;
  const octets = match.slice(1).map(Number);
  if (octets.some((n) => n > 255)) return false;
  const [a, b] = octets;
  return (
    a === 127 || // loopback
    a === 10 || // 10.0.0.0/8
    (a === 172 && b >= 16 && b <= 31) || // 172.16.0.0/12
    (a === 192 && b === 168) || // 192.168.0.0/16
    (a === 169 && b === 254) // link-local
  );
}

function isLocalIpv6(addr: string): boolean {
  if (addr === "::1") return true;
  if (/^f[cd]/.test(addr)) return true; // fc00::/7 unique local
  if (/^fe[89ab]/.test(addr)) return true; // fe80::/10 link-local
  return false;
}

/**
 * True when the endpoint is on this machine or the local network: localhost, 127.0.0.0/8, ::1, *.local, private
 * IPv4 ranges and IPv6 unique-local or link-local addresses. An empty or unparseable URL is treated as not local.
 */
export function isLocalEndpoint(baseUrl: string): boolean {
  let url: URL;
  try {
    url = new URL(baseUrl.trim());
  } catch {
    return false;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  const host = url.hostname.toLowerCase();
  if (!host) return false;
  if (host.startsWith("[") && host.endsWith("]")) return isLocalIpv6(host.slice(1, -1));
  if (isLocalIpv4(host)) return true;
  return host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local");
}
