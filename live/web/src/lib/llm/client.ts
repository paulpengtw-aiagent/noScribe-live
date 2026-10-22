// Chat client for an OpenAI-compatible endpoint. The browser calls the endpoint directly; there is no server proxy.
// Anthropic endpoints (see isAnthropicEndpoint) get extra headers and body rules; every other host gets the plain request.
import { ANTHROPIC_BROWSER_HEADER, ANTHROPIC_MAX_TOKENS, ANTHROPIC_VERSION, isAnthropicEndpoint } from "./anthropic";
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
  /** Ask the endpoint for a JSON object reply (response_format json_object). Not sent to Anthropic endpoints. */
  json?: boolean;
  maxTokens?: number;
}

/**
 * Result of testConnection. Anthropic endpoints are checked with the models list, other hosts with a tiny chat call.
 * `modelListed` and `models` are set only for Anthropic endpoints.
 */
export type TestConnectionResult =
  | {
      ok: true;
      ms: number;
      model: string;
      provider: "anthropic" | "openai";
      modelListed?: boolean;
      models?: string[];
    }
  | { ok: false; error: LlmError };

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

/** The Anthropic models list URL. One page of up to 1000 models. */
function modelsUrl(baseUrl: string): string {
  return `${baseUrl.trim().replace(/\/+$/, "")}/models?limit=1000`;
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

/** The error kind for a non-2xx status. */
function kindForStatus(status: number): LlmErrorKind {
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 429) return "rate_limit";
  if (status === 529) return "overloaded";
  return "http";
}

/** The LlmError for a fetch that threw: "aborted" for a cancel, "cors" for a probable CORS block, else "network". */
function fetchFailure(err: unknown, url: string, signal?: AbortSignal): LlmError {
  if (signal?.aborted || isAbortError(err)) return fail("aborted", "The request was canceled.");
  if (err instanceof TypeError) {
    if (isLikelyCorsBlock(url)) {
      return fail(
        "cors",
        `The browser blocked the request to ${url}. The endpoint must allow cross-origin requests from ${window.location.origin} (CORS).`,
      );
    }
    return fail("network", `Could not reach ${url}: ${err.message}`);
  }
  return fail("network", `Request to ${url} failed: ${String(err)}`);
}

/** The `error` message of a JSON error body, with `error.type` in front when present. Null when there is none. */
function errorMessageOf(raw: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  // Covers OpenAI-shaped {"error":{"message"}} and Anthropic {"type":"error","error":{"type","message"}}.
  const error = (parsed as { error?: unknown } | null)?.error;
  if (typeof error === "string") return error.trim() || null;
  if (typeof error !== "object" || error === null) return null;
  const { type, message } = error as { type?: unknown; message?: unknown };
  const parts = [type, message]
    .filter((p): p is string => typeof p === "string" && p.trim() !== "")
    .map((p) => p.trim());
  return parts.length > 0 ? parts.join(": ") : null;
}

/** A short excerpt of an error body, with the key removed. Uses the error message when the body has one. */
async function bodyExcerpt(res: Response, apiKey: string): Promise<string> {
  try {
    let text = (await res.text()).replace(/\s+/g, " ").trim();
    text = errorMessageOf(text) ?? text;
    // Never echo the key back into an error message, even if the server reflects it.
    if (apiKey) text = text.split(apiKey).join("[key]");
    return Array.from(text).slice(0, EXCERPT_CHARS).join("");
  } catch {
    return "";
  }
}

/** The LlmError for a non-2xx reply: the status, a short body excerpt, and the kind for the status. */
async function httpFailure(res: Response, apiKey: string, signal?: AbortSignal): Promise<LlmError> {
  const excerpt = await bodyExcerpt(res, apiKey);
  if (signal?.aborted) return fail("aborted", "The request was canceled.");
  const message = excerpt ? `HTTP ${res.status}: ${excerpt}` : `HTTP ${res.status}`;
  return fail(kindForStatus(res.status), message, res.status);
}

/**
 * One chat completion. Returns the first choice's message content. Throws an LlmError (a plain object, not an Error):
 * "aborted" for a cancel, "cors" for a probable CORS block, "network" for other fetch failures, "auth" for 401,
 * "forbidden" for 403, "rate_limit" for 429, "overloaded" for 529, "http" for other non-2xx replies, and "json" when the
 * reply does not have the expected shape. On Anthropic endpoints the request also carries the browser-access header,
 * never sends temperature, top_p or response_format, and sends max_tokens of at least ANTHROPIC_MAX_TOKENS.
 */
export async function chatCompletion(opts: ChatCompletionOptions): Promise<string> {
  const { settings, messages, signal, json, maxTokens } = opts;
  const key = opts.apiKey.trim();
  if (!settings.baseUrl.trim()) throw fail("network", "No base URL is set for the LLM endpoint.");

  const anthropic = isAnthropicEndpoint(settings.baseUrl);
  const url = completionsUrl(settings.baseUrl);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (anthropic) headers[ANTHROPIC_BROWSER_HEADER] = "true";
  if (key) headers.Authorization = `Bearer ${key}`;

  const body: Record<string, unknown> = { model: settings.model, messages };
  if (anthropic) {
    body.max_tokens = Math.max(maxTokens ?? 0, ANTHROPIC_MAX_TOKENS);
  } else {
    if (settings.temperature !== undefined) body.temperature = settings.temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;
    if (json) body.response_format = { type: "json_object" };
  }

  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (err) {
    throw fetchFailure(err, url, signal);
  }

  if (!res.ok) throw await httpFailure(res, key, signal);

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

/**
 * Checks the endpoint and the key. Anthropic endpoints get one models-list request (no Authorization header), and the
 * result says whether settings.model is listed. Other hosts get a tiny chat call (max_tokens 5, "ping"). Reports the
 * round-trip time and never rejects.
 */
export async function testConnection(
  settings: LlmSettings,
  apiKey: string,
  signal?: AbortSignal,
): Promise<TestConnectionResult> {
  if (isAnthropicEndpoint(settings.baseUrl)) return testAnthropic(settings, apiKey, signal);
  const started = performance.now();
  try {
    await chatCompletion({
      settings,
      apiKey,
      messages: [{ role: "user", content: "ping" }],
      maxTokens: 5,
      signal,
    });
    return { ok: true, ms: Math.round(performance.now() - started), model: settings.model, provider: "openai" };
  } catch (err) {
    return { ok: false, error: isLlmError(err) ? err : fail("network", String(err)) };
  }
}

/** The Anthropic check: one GET of the models list with the native headers. Never rejects. */
async function testAnthropic(
  settings: LlmSettings,
  apiKey: string,
  signal?: AbortSignal,
): Promise<TestConnectionResult> {
  const started = performance.now();
  try {
    const models = await listAnthropicModels(settings, apiKey, signal);
    return {
      ok: true,
      ms: Math.round(performance.now() - started),
      model: settings.model,
      provider: "anthropic",
      modelListed: models.includes(settings.model),
      models,
    };
  } catch (err) {
    return { ok: false, error: isLlmError(err) ? err : fail("network", String(err)) };
  }
}

/** The ids in the Anthropic models list. Throws LlmError. */
async function listAnthropicModels(settings: LlmSettings, apiKey: string, signal?: AbortSignal): Promise<string[]> {
  const key = apiKey.trim();
  const url = modelsUrl(settings.baseUrl);
  const headers: Record<string, string> = {
    "x-api-key": key,
    "anthropic-version": ANTHROPIC_VERSION,
    [ANTHROPIC_BROWSER_HEADER]: "true",
  };

  let res: Response;
  try {
    res = await fetch(url, { method: "GET", headers, signal });
  } catch (err) {
    throw fetchFailure(err, url, signal);
  }
  if (!res.ok) throw await httpFailure(res, key, signal);

  let payload: unknown;
  try {
    payload = await res.json();
  } catch (err) {
    if (signal?.aborted || isAbortError(err)) throw fail("aborted", "The request was canceled.");
    throw fail("json", "The models reply was not valid JSON.");
  }
  const data = (payload as { data?: unknown } | null)?.data;
  if (!Array.isArray(data)) throw fail("json", "The models reply has no data array.");
  const ids: string[] = [];
  for (const entry of data as unknown[]) {
    const id = (entry as { id?: unknown } | null)?.id;
    if (typeof id === "string") ids.push(id);
  }
  return ids;
}
