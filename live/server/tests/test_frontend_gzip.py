"""Gzip for the static frontend: text-like files over 1 KB, only for clients that accept gzip, never /api/.

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

import gzip

import pytest
from fastapi.testclient import TestClient

from server.app import create_app

BIG_JS = ("console.log('noScribe live viewer');\n" * 200).encode()   # about 7 KB, compresses well
BIG_CSS = ("body{color:#222}\n" * 200).encode()


@pytest.fixture()
def client(tmp_path):
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_bytes(b"<!doctype html><title>app</title>" + b"<p>viewer</p>" * 200)
    (static / "assets" / "index-test.js").write_bytes(BIG_JS)
    (static / "assets" / "index-test.css").write_bytes(BIG_CSS)
    (static / "assets" / "tiny.js").write_bytes(b"console.log(1);")
    (static / "assets" / "font.woff2").write_bytes(BIG_JS)   # big, but a font type: never compressed
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    return TestClient(create_app(feeds, static))


def test_js_is_sent_as_gzip_bytes_to_a_gzip_client(client):
    with client.stream("GET", "/assets/index-test.js", headers={"Accept-Encoding": "gzip"}) as response:
        raw = b"".join(response.iter_raw())
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["content-type"].startswith(("text/javascript", "application/javascript"))
    assert len(raw) < len(BIG_JS)
    assert gzip.decompress(raw) == BIG_JS


def test_css_is_gzipped_with_its_media_type(client):
    response = client.get("/assets/index-test.css", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-type"].startswith("text/css")
    assert response.content == BIG_CSS    # httpx decodes the body; a body that is not gzip would fail here


def test_the_spa_fallback_html_is_gzipped(client):
    response = client.get("/viewer/some-run", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-type"].startswith("text/html")
    assert response.content.startswith(b"<!doctype html>")


@pytest.mark.parametrize("accept_encoding", ["identity", "gzip;q=0", "br"])
def test_without_gzip_offered_the_js_is_identity(client, accept_encoding):
    with client.stream("GET", "/assets/index-test.js", headers={"Accept-Encoding": accept_encoding}) as response:
        raw = b"".join(response.iter_raw())
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["vary"] == "Accept-Encoding"    # identity copy still varies, so caches keep it apart
    assert raw == BIG_JS


@pytest.mark.parametrize("path", ["/assets/tiny.js", "/assets/font.woff2"])
def test_small_files_and_fonts_are_never_compressed(client, path):
    response = client.get(path, headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_a_conditional_get_for_the_gzip_copy_gets_304(client):
    first = client.get("/assets/index-test.css", headers={"Accept-Encoding": "gzip"})
    again = client.get(
        "/assets/index-test.css", headers={"Accept-Encoding": "gzip", "If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
    assert again.content == b""


def test_unknown_api_path_is_never_compressed(client):
    response = client.get("/api/nope", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 404
    assert "content-encoding" not in response.headers


def test_api_stream_is_never_compressed(client):
    with client.stream("GET", "/api/stream", headers={"Accept-Encoding": "gzip"}) as response:
        first = next(response.iter_raw())
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert "content-encoding" not in response.headers
    assert first.startswith(b"retry: 1500")
