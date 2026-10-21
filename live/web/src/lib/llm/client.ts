// Chat client for an OpenAI-compatible endpoint. The browser calls the endpoint directly; there is no server proxy.
import type { LlmError, LlmErrorKind, LlmSettings } from "./types";

/** One chat message in the OpenAI chat format. */
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ChatCompletionOptions {
  settings: LlmSettings;
  apiKey: string;
  messages: ChatMessage[];
  signal?: AbortSignal;
  /** Ask the endpoint for a JSON object reply (response_format json_object). */
  json?: boolean;
  maxTokens?: number;
}

export type TestConnectionResult = { ok: true; ms: number; model: string } | { ok: false; error: LlmError };

/** Most body characters kept in an error message. */
const EXCERPT_CHARS = 200;

interface ChatCompletionBody {
  choices?: { message?: { content?: unknown } }[];
}

function fail(kind: LlmErrorKind, message: string, status?: number): LlmError {
  return status === undefined ? { kind, message } : { kind, message, status };
}

function isAbortError(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { name?: unknown }).name === "AbortError";
}

function isLlmError(err: unknown): err is LlmError {
  return typeof err === "object" && err !== null && "kind" in err && "message" in err;
}

/** The chat completions URL for a base URL such as http://localhost:8799/v1 (any trailing slashes are dropped). */
function completionsUrl(baseUrl: string): string {
  return `${baseUrl.trim().replace(/\/+$/, "")}/chat/completions`;
}

/** A fetch TypeError on a cross-origin page while the browser is online is most often a CORS block. */
function isLikelyCorsBlock(url: string): boolean {
  let origin: string;
  try {
    origin = new URL(url).origin;
  } catch {
    return false;
  }
  return origin !== window.location.origin && navigator.onLine === true;
}

async function bodyExcerpt(res: Response, apiKey: string): Promise<string> {
  try {
    let text = (await res.text()).replace(/\s+/g, " ").trim();
    // Never echo the key back into an error message, even if the server reflects it.
    if (apiKey) text = text.split(apiKey).join("[key]");
    return Array.from(text).slice(0, EXCERPT_CHARS).join("");
  } catch {
    return "";
  }
}

/**
 * One chat completion. Returns the first choice's message content. Throws an LlmError (a plain object, not an Error):
 * "aborted" for a cancel, "cors" for a probable CORS block, "network" for other fetch failures, "auth" for 401 and 403,
 * "http" for other non-2xx replies, and "json" when the reply does not have the expected shape.
 */
export async function chatCompletion(opts: ChatCompletionOptions): Promise<string> {
  const { settings, messages, signal, json, maxTokens } = opts;
  const key = opts.apiKey.trim();
  if (!settings.baseUrl.trim()) throw fail("network", "No base URL is set for the LLM endpoint.");

  const url = completionsUrl(settings.baseUrl);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (key) headers.Authorization = `Bearer ${key}`;

  const body: Record<string, unknown> = { model: settings.model, messages };
  if (settings.temperature !== undefined) body.temperature = settings.temperature;
  if (maxTokens !== undefined) body.max_tokens = maxTokens;
  if (json) body.response_format = { type: "json_object" };

  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (err) {
    if (signal?.aborted || isAbortError(err)) throw fail("aborted", "The request was canceled.");
    if (err instanceof TypeError) {
      if (isLikelyCorsBlock(url)) {
        throw fail(
          "cors",
          `The browser blocked the request to ${url}. The endpoint must allow cross-origin requests from ${window.location.origin} (CORS).`,
        );
      }
      throw fail("network", `Could not reach ${url}: ${err.message}`);
    }
    throw fail("network", `Request to ${url} failed: ${String(err)}`);
  }

  if (!res.ok) {
    const excerpt = await bodyExcerpt(res, key);
    if (signal?.aborted) throw fail("aborted", "The request was canceled.");
    const message = excerpt ? `HTTP ${res.status}: ${excerpt}` : `HTTP ${res.status}`;
    throw fail(res.status === 401 || res.status === 403 ? "auth" : "http", message, res.status);
  }

  let payload: unknown;
  try {
    payload = await res.json();
  } catch (err) {
    if (signal?.aborted || isAbortError(err)) throw fail("aborted", "The request was canceled.");
    throw fail("json", "The endpoint reply was not valid JSON.");
  }
  const content = (payload as ChatCompletionBody | null)?.choices?.[0]?.message?.content;
  if (typeof content !== "string") {
    throw fail("json", "The endpoint reply has no choices[0].message.content string.");
  }
  return content;
}

/** A tiny chat call (max_tokens 5, "ping") that reports the round-trip time. Never rejects. */
export async function testConnection(
  settings: LlmSettings,
  apiKey: string,
  signal?: AbortSignal,
): Promise<TestConnectionResult> {
  const started = performance.now();
  try {
    await chatCompletion({
      settings,
      apiKey,
      messages: [{ role: "user", content: "ping" }],
      maxTokens: 5,
      signal,
    });
    return { ok: true, ms: Math.round(performance.now() - started), model: settings.model };
  } catch (err) {
    return { ok: false, error: isLlmError(err) ? err : fail("network", String(err)) };
  }
}
