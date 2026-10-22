// Anthropic endpoint support. The chat endpoint is OpenAI-compatible; the models list is Anthropic's native API.
// This module has no runtime imports, so the constants and helpers are safe to import from anywhere.

/** Base URL of Anthropic's OpenAI-compatible chat endpoint. */
export const ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1";
/** Model selected by default for Anthropic endpoints. */
export const ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5";
/** Minimum max_tokens for Anthropic requests. The model thinks by default and thinking counts against this budget. */
export const ANTHROPIC_MAX_TOKENS = 16000;
/** Value of the `anthropic-version` header on the native API. */
export const ANTHROPIC_VERSION = "2023-06-01";
/** Header that lets a browser call the Anthropic API directly. Without it the CORS preflight is refused. */
export const ANTHROPIC_BROWSER_HEADER = "anthropic-dangerous-direct-browser-access";
/**
 * localStorage key for a comma-separated list of extra `host:port` values that are treated as Anthropic endpoints.
 * This is a test-only override with no UI.
 */
export const ANTHROPIC_DEV_HOSTS_KEY = "noscribe-live-llm-dev-anthropic-hosts";

const ANTHROPIC_HOSTNAME = "api.anthropic.com";

/** The extra dev hosts from localStorage, trimmed and lowercased. Empty when storage is unavailable or unset. */
function devHosts(): string[] {
  try {
    const raw = window.localStorage.getItem(ANTHROPIC_DEV_HOSTS_KEY);
    if (!raw) return [];
    return raw
      .split(",")
      .map((h) => h.trim().toLowerCase())
      .filter((h) => h !== "");
  } catch {
    // Storage is unavailable, or there is no window: no dev hosts.
    return [];
  }
}

/**
 * True when the base URL is Anthropic's API: the hostname is api.anthropic.com (any path or port), or the `host`
 * (hostname:port) is listed in localStorage[ANTHROPIC_DEV_HOSTS_KEY]. An invalid URL is not an Anthropic endpoint.
 */
export function isAnthropicEndpoint(baseUrl: string): boolean {
  let url: URL;
  try {
    url = new URL(baseUrl.trim());
  } catch {
    return false;
  }
  if (url.hostname.toLowerCase() === ANTHROPIC_HOSTNAME) return true;
  return devHosts().includes(url.host.toLowerCase());
}
