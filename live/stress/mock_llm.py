#!/usr/bin/env python3
"""Stdlib OpenAI-compatible mock for the noScribe Live LLM correction stress checks. Never calls a real API.

Run it (from any directory) and point the viewer at it:

    python3 live/stress/mock_llm.py --port 8799          # default port 8799, bind 127.0.0.1
    base URL http://localhost:8799/v1, any API key, model "mock"
    python3 live/stress/mock_llm.py --port 8799 --anthropic   # Anthropic emulation, see below

Endpoints
  POST /v1/chat/completions   (also accepted without /v1)  -> chat.completion JSON, stream is never used
  GET  /v1/models            -> a static list (handy as a health check)
  OPTIONS *                  -> 204 (CORS preflight)

Behaviour
  * No segment lines in any user message and the last user message contains the word "ping": content "pong"
    (connection test).
  * Otherwise the segment lines of the batch prompt, `[#<index>] [m:ss] <speaker>: <text>`, are corrected
    deterministically. The batch prompt is every user message read from its "Segments to correct:" header on
    (a repair retry resends the batch, so its key and corrections are the same). Only segment_ids present in
    that batch can appear in the answer:
      - "LibriVox dot org"                          -> "LibriVox.org"           reason "URL"
      - "吶喊自恤"                                   -> "吶喊自序"                 reason "書名（依參考文件）"
      - text starting with "訓 "                     -> prefix removed           reason "誤辨識"
      - "Gettysburg Address by Abraham Lincoln" line -> "." appended if missing  reason "標點"
    The content is a JSON array of
      {"segment_id": <int>, "original": <str>, "corrected": <str>, "reason": <str>}
    in transcript order; a segment without a change is left out.
  * Model names switch the mode:
      "mock-malformed-once": the FIRST request per process for each batch (batch = the sorted set of
          segment_ids) answers with the invalid JSON "Sure! [{segment_id: 1,,]"; later requests for that
          batch answer validly (retry check).
      "mock-error-500": every chat request answers HTTP 500 with an OpenAI-style error body.
  * CORS: by default every response carries
      Access-Control-Allow-Origin: *
      Access-Control-Allow-Headers: authorization, content-type
      Access-Control-Allow-Methods: POST, OPTIONS
    `--no-cors` omits these headers, so a browser fails the request (CORS error check).

Anthropic mode (`--anthropic`) emulates Anthropic's OpenAI-compatible endpoint and its native models API, as
verified against the real service. Nothing is sent anywhere.
  * CORS preflight (OPTIONS): without "anthropic-dangerous-direct-browser-access" in Access-Control-Request-Headers
    -> 400 and NO Access-Control-Allow-Origin, so the browser reports a CORS error. With it -> 200,
    Access-Control-Allow-Origin *, Access-Control-Allow-Headers echoing the requested headers, methods
    GET, POST, OPTIONS. Actual responses carry Access-Control-Allow-Origin *.
  * POST /v1/chat/completions: the key is the Authorization Bearer token. A missing or empty key, or sk-ant-401
    -> 401 authentication_error; sk-ant-403 -> 403 permission_error; sk-ant-429 -> 429 rate_limit_error;
    sk-ant-529 -> 529 overloaded_error. Errors use the OpenAI-style body {"error": {"code", "message", "type"}}.
    temperature below 1 -> 400; any top_p (not null) -> 400; response_format is ignored. Correction replies wrap
    the JSON array in a ```json fence with a sentence of prose before and after; the connection test's "pong" is
    not wrapped. Other keys are valid.
  * GET /v1/models: the native API. The key is the x-api-key header, and anthropic-version must be 2023-06-01
    (else 400). No x-api-key (for example only a Bearer) -> 401 {"type": "error", "error": {"type":
    "authentication_error", "message": "invalid x-api-key"}}. sk-ant-401/403/429/529 as above. sk-ant-nomodel ->
    the list without claude-opus-5-5. Other keys -> claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5.
  * Model names still switch the correction mode ("mock-malformed-once", "mock-error-500") as above.

Logging: one line per request on stderr (method, path, outcome). The key is never logged; the Authorization
and x-api-key headers are only read for their kind (bearer, x-api-key, none).
  * normal mode: the lines above; chat lines also carry browser_header=yes|no (whether the request has the
    anthropic-dangerous-direct-browser-access header).
  * anthropic mode: METHOD PATH mode=anthropic browser_header=yes|no auth=bearer|x-api-key|none; for chat also
    model, temperature=absent|<value>, top_p=absent|present, max_tokens=<n>|absent,
    response_format=absent|present, segments, response=<kind>, status. For OPTIONS, browser_header says whether
    the preflight asks for the header.
Use `--log FILE` to write the same lines to a file (appended).
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SEG_RE = re.compile(r"^\[#(\d+)\]\s*\[[\d:]+\]\s*([^:\n]*?):\s?(.*)$")
PING_RE = re.compile(r"\bping\b", re.IGNORECASE)
MALFORMED_TEXT = "Sure! [{segment_id: 1,,]"
CORS_HEADERS = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Headers", "authorization, content-type"),
    ("Access-Control-Allow-Methods", "POST, OPTIONS"),
)
BROWSER_HEADER = "anthropic-dangerous-direct-browser-access"  # sent by browsers only for direct API calls
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODELS = (("claude-opus-5-5", "Claude Opus 5.5"), ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
                    ("claude-haiku-5-5", "Claude Haiku 5.5"))
ANTHROPIC_KEY_ERRORS = {  # key -> (HTTP status, error type, message)
    "sk-ant-401": (401, "authentication_error", "invalid x-api-key"),
    "sk-ant-403": (403, "permission_error", "your API key does not have permission to use the specified resource"),
    "sk-ant-429": (429, "rate_limit_error", "rate limit exceeded (mock)"),
    "sk-ant-529": (529, "overloaded_error", "Overloaded (mock)"),
}
FENCE_BEFORE = "Here is the JSON array of corrections for this batch:\n```json\n"
FENCE_AFTER = "\n```\nOnly the segments listed above are corrected; the other segments stay as they are."

_lock = threading.Lock()
_seen_batches: set[tuple[int, ...]] = set()
_counter = itertools.count(1)
_log_file: Any = None
_no_cors = False
_anthropic = False


def log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    text = f"{stamp} {line}"
    print(text, file=sys.stderr, flush=True)
    if _log_file is not None:
        _log_file.write(text + "\n")
        _log_file.flush()


def parse_segments(text: str) -> list[tuple[int, str]]:
    segments: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = SEG_RE.match(line.strip())
        if match:
            segments.append((int(match.group(1)), match.group(3)))
    return segments


def correct(text: str) -> tuple[str, list[str]]:
    """Deterministic correction of one segment text. Returns (corrected text, reasons)."""
    reasons: list[str] = []
    fixed = text
    if "LibriVox dot org" in fixed:
        fixed = fixed.replace("LibriVox dot org", "LibriVox.org")
        reasons.append("URL")
    if "吶喊自恤" in fixed:
        fixed = fixed.replace("吶喊自恤", "吶喊自序")
        reasons.append("書名（依參考文件）")
    if fixed.startswith("訓 "):
        fixed = fixed[len("訓 "):]
        reasons.append("誤辨識")
    if "Gettysburg Address by Abraham Lincoln" in fixed and not fixed.rstrip().endswith("."):
        fixed = fixed.rstrip() + "."
        reasons.append("標點")
    return fixed, reasons


def corrections_for(segments: list[tuple[int, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg_id, text in segments:
        fixed, reasons = correct(text)
        if fixed != text:
            out.append({"segment_id": seg_id, "original": text, "corrected": fixed,
                        "reason": "; ".join(reasons)})
    return out


BATCH_HEADER = "Segments to correct:"  # the batch prompt's section header (the read-only context is above it)


def user_texts(messages: list[Any]) -> list[str]:
    """The text of every user message, in order (OpenAI content may also be a list of parts)."""
    texts: list[str] = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, list):  # OpenAI content parts
                texts.append("\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict)))
            else:
                texts.append(str(content))
    return texts


def last_user_text(messages: list[Any]) -> str:
    texts = user_texts(messages)
    return texts[-1] if texts else ""


def batch_segments(messages: list[Any]) -> list[tuple[int, str]]:
    """The segment lines of the batch prompt. The app's repair retry is [system, user(batch), assistant(bad reply),
    user(repair instruction)]; a real model reads the whole conversation, so every user message is read, and the
    batch lines are those below BATCH_HEADER."""
    segments: list[tuple[int, str]] = []
    for text in user_texts(messages):
        if BATCH_HEADER in text:
            text = text.split(BATCH_HEADER, 1)[1]
        segments.extend(parse_segments(text))
    return segments


def chat_payload(model: str, content: str, prompt_chars: int) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-mock-{next(_counter)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": max(1, prompt_chars // 2), "completion_tokens": max(1, len(content) // 2),
                  "total_tokens": max(1, prompt_chars // 2) + max(1, len(content) // 2)},
    }


def browser_flag(handler: BaseHTTPRequestHandler) -> str:
    """yes when the request carries the browser-access header."""
    return "yes" if handler.headers.get(BROWSER_HEADER) is not None else "no"


def auth_kind(handler: BaseHTTPRequestHandler) -> str:
    """The credential kind the request carries (never its value)."""
    if handler.headers.get("x-api-key") is not None:
        return "x-api-key"
    if (handler.headers.get("Authorization") or "").startswith("Bearer "):
        return "bearer"
    return "none"


def bearer_key(handler: BaseHTTPRequestHandler) -> str:
    value = handler.headers.get("Authorization") or ""
    return value[len("Bearer "):].strip() if value.startswith("Bearer ") else ""


def compat_error(kind: str, message: str) -> dict[str, Any]:
    """The OpenAI-compatible error body the chat endpoint answers with."""
    return {"error": {"code": kind, "message": message, "type": kind}}


def native_error(kind: str, message: str) -> dict[str, Any]:
    """The native API error body (GET /v1/models)."""
    return {"type": "error", "error": {"type": kind, "message": message}}


def fenced_reply(json_text: str) -> str:
    return FENCE_BEFORE + json_text + FENCE_AFTER


def temperature_rejected(value: Any) -> bool:
    """The endpoint answers 400 for a temperature below 1 (a value that is not a number is refused too)."""
    if value is None:
        return False
    try:
        return float(value) < 1
    except (TypeError, ValueError):
        return True


def anthropic_models(key: str) -> list[dict[str, Any]]:
    models = [{"type": "model", "id": mid, "display_name": name, "created_at": "2026-01-01T00:00:00Z"}
              for mid, name in ANTHROPIC_MODELS]
    if key == "sk-ant-nomodel":
        models = [m for m in models if m["id"] != "claude-opus-5-5"]
    return models


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-llm/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence the default access log (we log ourselves)
        return

    def _cors(self) -> None:
        if _no_cors:
            return
        if _anthropic:  # actual responses need only the origin for a browser call
            self.send_header("Access-Control-Allow-Origin", "*")
            return
        for name, value in CORS_HEADERS:
            self.send_header(name, value)

    def _send(self, status: int, payload: Any, cors: bool = True) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if cors:
            self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 (stdlib naming)
        if _anthropic:
            self._anthropic_preflight()
            return
        log(f"OPTIONS {self.path} preflight status=204 cors={'off' if _no_cors else 'on'}")
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _anthropic_preflight(self) -> None:
        requested = self.headers.get("Access-Control-Request-Headers") or ""
        asked = {part.strip().lower() for part in requested.split(",")}
        if BROWSER_HEADER not in asked:
            log(f"OPTIONS {self.path} mode=anthropic browser_header=no auth=none status=400")
            self._send(400, compat_error("invalid_request_error",
                                         f"CORS request rejected: the {BROWSER_HEADER} header is required"),
                       cors=False)
            return
        cors = "off" if _no_cors else "on"
        log(f"OPTIONS {self.path} mode=anthropic browser_header=yes auth=none status=200 cors={cors}")
        self.send_response(200)
        if not _no_cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", requested)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if _anthropic:
            self._anthropic_models(path)
            return
        if path in ("/v1/models", "/models"):
            log(f"GET {path} status=200")
            self._send(200, {"object": "list", "data": [{"id": "mock", "object": "model", "owned_by": "mock"}]})
            return
        log(f"GET {path} status=404")
        self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def _anthropic_models(self, path: str) -> None:
        prefix = f"GET {path} mode=anthropic browser_header={browser_flag(self)} auth={auth_kind(self)}"
        if path not in ("/v1/models", "/models"):
            log(f"{prefix} status=404")
            self._send(404, native_error("not_found_error", "not found"))
            return
        key = self.headers.get("x-api-key") or ""
        if not key:
            log(f"{prefix} status=401 error=authentication_error")
            self._send(401, native_error("authentication_error", "invalid x-api-key"))
            return
        if self.headers.get("anthropic-version") != ANTHROPIC_VERSION:
            log(f"{prefix} status=400 error=invalid_request_error")
            self._send(400, native_error("invalid_request_error", f"anthropic-version must be {ANTHROPIC_VERSION}"))
            return
        if key in ANTHROPIC_KEY_ERRORS:
            status, kind, message = ANTHROPIC_KEY_ERRORS[key]
            log(f"{prefix} status={status} error={kind}")
            self._send(status, native_error(kind, message))
            return
        models = anthropic_models(key)
        log(f"{prefix} models={len(models)} status=200")
        self._send(200, {"data": models, "has_more": False, "first_id": models[0]["id"],
                         "last_id": models[-1]["id"]})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            if _anthropic:
                log(f"POST {path} mode=anthropic browser_header={browser_flag(self)} auth={auth_kind(self)} status=404")
            else:
                log(f"POST {path} status=404")
            self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if _anthropic:
            self._anthropic_chat(path, raw)
            return
        browser = browser_flag(self)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            log(f"POST {path} browser_header={browser} status=400 reason=bad-json")
            self._send(400, {"error": {"message": "request body is not JSON", "type": "invalid_request_error"}})
            return
        model = str(body.get("model") or "mock")
        messages = body.get("messages") or []
        user = last_user_text(messages)
        segments = batch_segments(messages)
        seg_ids = tuple(sorted({sid for sid, _ in segments}))

        if model == "mock-error-500":
            log(f"POST {path} browser_header={browser} model={model} segments={len(segments)} status=500")
            self._send(500, {"error": {"message": "mock-error-500: injected server error", "type": "server_error"}})
            return

        if not segments and PING_RE.search(user):
            content, outcome = "pong", "ping"
        else:
            if model == "mock-malformed-once":
                with _lock:
                    first = seg_ids not in _seen_batches
                    _seen_batches.add(seg_ids)
                if first:
                    content, outcome = MALFORMED_TEXT, "malformed"
                else:
                    content = json.dumps(corrections_for(segments), ensure_ascii=False)
                    outcome = "valid-retry"
            else:
                content = json.dumps(corrections_for(segments), ensure_ascii=False)
                outcome = "valid"

        payload = chat_payload(model, content, len(user))
        log(f"POST {path} browser_header={browser} model={model} segments={len(segments)} response={outcome} "
            "status=200")
        self._send(200, payload)

    def _anthropic_chat(self, path: str, raw: bytes) -> None:
        prefix = f"POST {path} mode=anthropic browser_header={browser_flag(self)} auth={auth_kind(self)}"
        key = bearer_key(self)
        failure = ANTHROPIC_KEY_ERRORS.get(key) if key else (401, "authentication_error", "invalid x-api-key")
        if failure:
            status, kind, message = failure
            log(f"{prefix} response=error error={kind} status={status}")
            self._send(status, compat_error(kind, message))
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            log(f"{prefix} response=error error=invalid_request_error status=400 reason=bad-json")
            self._send(400, compat_error("invalid_request_error", "request body is not a JSON object"))
            return
        model = str(body.get("model") or "mock")
        temperature = body.get("temperature")
        top_p = body.get("top_p")
        max_tokens = body.get("max_tokens")
        response_format = body.get("response_format")  # ignored by the endpoint
        messages = body.get("messages") or []
        user = last_user_text(messages)
        segments = batch_segments(messages)
        seg_ids = tuple(sorted({sid for sid, _ in segments}))
        fields = (f"model={model} temperature={'absent' if temperature is None else temperature} "
                  f"top_p={'absent' if top_p is None else 'present'} "
                  f"max_tokens={'absent' if max_tokens is None else max_tokens} "
                  f"response_format={'absent' if response_format is None else 'present'} "
                  f"segments={len(segments)}")
        problem = ("temperature must be 1 or greater for this model (mock)" if temperature_rejected(temperature)
                   else "top_p is not supported for this model (mock)" if top_p is not None else "")
        if problem:
            log(f"{prefix} {fields} response=error error=invalid_request_error status=400")
            self._send(400, compat_error("invalid_request_error", problem))
            return
        if model == "mock-error-500":
            log(f"{prefix} {fields} response=error error=server_error status=500")
            self._send(500, {"error": {"message": "mock-error-500: injected server error", "type": "server_error"}})
            return

        fenced = False
        if not segments and PING_RE.search(user):
            content, outcome = "pong", "ping"
        else:
            if model == "mock-malformed-once":
                with _lock:
                    first = seg_ids not in _seen_batches
                    _seen_batches.add(seg_ids)
            else:
                first = False
            if model == "mock-malformed-once" and first:
                content, outcome = MALFORMED_TEXT, "malformed"
            else:
                content = fenced_reply(json.dumps(corrections_for(segments), ensure_ascii=False))
                outcome = "valid-retry" if model == "mock-malformed-once" else "valid"
                fenced = True
        log(f"{prefix} {fields} response={outcome}{' reply=fenced' if fenced else ''} status=200")
        self._send(200, chat_payload(model, content, len(user)))


def main(argv: list[str] | None = None) -> int:
    global _no_cors, _log_file, _anthropic
    parser = argparse.ArgumentParser(description="OpenAI-compatible mock LLM for noScribe Live checks.")
    parser.add_argument("--port", type=int, default=8799, help="listen port (default 8799)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--no-cors", action="store_true", help="omit the CORS headers (browser CORS failure)")
    parser.add_argument("--anthropic", action="store_true",
                        help="emulate Anthropic's endpoint: browser-header CORS rule, key-driven statuses, "
                             "native /v1/models, temperature/top_p rules, fenced replies")
    parser.add_argument("--log", default="", help="also append the request log to this file")
    args = parser.parse_args(argv)
    _no_cors = args.no_cors
    _anthropic = args.anthropic
    if args.log:
        _log_file = open(args.log, "a", encoding="utf-8")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    mode = " mode=anthropic" if _anthropic else ""
    log(f"mock-llm listening on http://{args.host}:{args.port}/v1 cors={'off' if _no_cors else 'on'}{mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
