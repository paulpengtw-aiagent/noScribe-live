#!/usr/bin/env python3
"""Stdlib OpenAI-compatible mock for the noScribe Live LLM correction stress checks. Never calls a real API.

Run it (from any directory) and point the viewer at it:

    python3 live/stress/mock_llm.py --port 8799          # default port 8799, bind 127.0.0.1
    base URL http://localhost:8799/v1, any API key, model "mock"

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

Logging: one line per request on stderr (method, path, model, segment count, outcome). The Authorization
header is never read into the log. Use `--log FILE` to write the same lines to a file (appended).
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

_lock = threading.Lock()
_seen_batches: set[tuple[int, ...]] = set()
_counter = itertools.count(1)
_log_file: Any = None
_no_cors = False


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


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-llm/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence the default access log (we log ourselves)
        return

    def _cors(self) -> None:
        if not _no_cors:
            for name, value in CORS_HEADERS:
                self.send_header(name, value)

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 (stdlib naming)
        log(f"OPTIONS {self.path} preflight status=204 cors={'off' if _no_cors else 'on'}")
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/v1/models", "/models"):
            log(f"GET {path} status=200")
            self._send(200, {"object": "list", "data": [{"id": "mock", "object": "model", "owned_by": "mock"}]})
            return
        log(f"GET {path} status=404")
        self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            log(f"POST {path} status=404")
            self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            log(f"POST {path} status=400 reason=bad-json")
            self._send(400, {"error": {"message": "request body is not JSON", "type": "invalid_request_error"}})
            return
        model = str(body.get("model") or "mock")
        messages = body.get("messages") or []
        user = last_user_text(messages)
        segments = batch_segments(messages)
        seg_ids = tuple(sorted({sid for sid, _ in segments}))

        if model == "mock-error-500":
            log(f"POST {path} model={model} segments={len(segments)} status=500")
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

        prompt_chars = len(user)
        payload = {
            "id": f"chatcmpl-mock-{next(_counter)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": max(1, prompt_chars // 2), "completion_tokens": max(1, len(content) // 2),
                      "total_tokens": max(1, prompt_chars // 2) + max(1, len(content) // 2)},
        }
        log(f"POST {path} model={model} segments={len(segments)} response={outcome} status=200")
        self._send(200, payload)


def main(argv: list[str] | None = None) -> int:
    global _no_cors, _log_file
    parser = argparse.ArgumentParser(description="OpenAI-compatible mock LLM for noScribe Live checks.")
    parser.add_argument("--port", type=int, default=8799, help="listen port (default 8799)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--no-cors", action="store_true", help="omit the CORS headers (browser CORS failure)")
    parser.add_argument("--log", default="", help="also append the request log to this file")
    args = parser.parse_args(argv)
    _no_cors = args.no_cors
    if args.log:
        _log_file = open(args.log, "a", encoding="utf-8")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    log(f"mock-llm listening on http://{args.host}:{args.port}/v1 cors={'off' if _no_cors else 'on'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
