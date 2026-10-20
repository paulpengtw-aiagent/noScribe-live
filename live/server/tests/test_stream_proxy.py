"""Proxy-friendly GET /api/stream: headers and an opening padding comment, so tunnels do not buffer it.

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import create_app


def _client(tmp_path) -> TestClient:
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    return TestClient(create_app(feeds, static))


def _read_until(response, marker: bytes, limit: int = 1 << 16) -> bytes:
    """Read the streamed body up to and including ``marker``. The limit keeps a regression from looping forever."""
    raw = b""
    for chunk in response.iter_raw():
        raw += chunk
        if marker in raw or len(raw) >= limit:
            break
    return raw


def test_the_stream_response_has_the_proxy_headers(tmp_path):
    with _client(tmp_path).stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        assert "content-encoding" not in response.headers    # no compression: a proxy would hold the body back


def test_the_stream_opens_with_a_2kb_comment_right_after_retry_and_before_hello(tmp_path):
    with _client(tmp_path).stream("GET", "/api/stream") as response:
        raw = _read_until(response, b"event: hello")

    retry = b"retry: 1500\n\n"
    assert raw.startswith(retry), raw[:100]
    assert b"event: hello" in raw, raw[:200]
    padding = raw[len(retry):raw.index(b"event: hello")]
    assert padding.startswith(b":") and padding.endswith(b"\n\n"), padding[:20]
    assert len(padding) >= 2048
    assert b"\n" not in padding[:-2]    # one comment line, so EventSource ignores it and nothing else is in it
