"""Tests for the optional token gate (``python -m server --token`` or LIVE_TOKEN).

Run from live/:  .venv/bin/python -m pytest
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import create_app

TOKEN = "s3cret-token"


@pytest.fixture
def dirs(tmp_path):
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    return feeds, static


def make_client(dirs, token=None) -> TestClient:
    feeds, static = dirs
    return TestClient(create_app(feeds, static, token=token))


def test_gate_off_serves_everything_as_before(dirs):
    client = make_client(dirs)
    assert client.get("/").status_code == 200
    assert client.get("/api/runs").json() == []
    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200


def test_gate_on_refuses_every_path_without_a_token(dirs):
    client = make_client(dirs, TOKEN)
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 401
    assert "text/html" in page.headers["content-type"] and "?token=" in page.text
    api = client.get("/api/runs", follow_redirects=False)
    assert api.status_code == 401 and api.json() == {"error": "unauthorized"}
    with client.stream("GET", "/api/stream", follow_redirects=False) as response:
        assert response.status_code == 401


def test_a_wrong_token_is_refused(dirs):
    client = make_client(dirs, TOKEN)
    assert client.get("/api/runs?token=wrong", follow_redirects=False).status_code == 401
    assert client.get("/api/runs", headers={"Cookie": "nslive_token=wrong"}).status_code == 401


def test_the_right_query_token_sets_a_cookie_and_redirects_without_it(dirs):
    client = make_client(dirs, TOKEN)
    response = client.get(f"/api/runs?token={TOKEN}&x=1", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/api/runs?x=1"
    cookie = response.headers["set-cookie"]
    assert f"nslive_token={TOKEN}" in cookie
    for attribute in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=604800"):
        assert attribute in cookie
    assert "Secure" not in cookie
    assert client.get("/api/runs").status_code == 200          # the cookie is now the credential


def test_the_cookie_opens_the_event_stream(dirs):
    client = make_client(dirs, TOKEN)
    client.get(f"/api/runs?token={TOKEN}")
    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200


def test_https_forwarded_requests_get_a_secure_cookie(dirs):
    client = make_client(dirs, TOKEN)
    response = client.get(f"/?token={TOKEN}", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert "Secure" in response.headers["set-cookie"]


def test_bearer_token_works_without_a_cookie(dirs):
    client = make_client(dirs, TOKEN)
    ok = client.get("/api/runs", headers={"Authorization": f"Bearer {TOKEN}"}, follow_redirects=False)
    assert ok.status_code == 200
    bad = client.get("/api/runs", headers={"Authorization": "Bearer nope"}, follow_redirects=False)
    assert bad.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Forwarded-Proto": "https"},
        {"X-Forwarded-Proto": "https, http"},
        {"Forwarded": "for=192.0.2.60;proto=https;by=203.0.113.43"},
        {"Forwarded": "proto=https"},
        {"X-Forwarded-Ssl": "on"},
        {"Origin": "https://viewer.example"},
        {"Referer": "https://viewer.example/some/page"},
    ],
)
def test_each_https_indicator_gives_a_secure_cookie(dirs, headers):
    client = make_client(dirs, TOKEN)
    response = client.get(f"/?token={TOKEN}", headers=headers, follow_redirects=False)
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


def test_an_https_request_url_gives_a_secure_cookie(dirs):
    feeds, static = dirs
    client = TestClient(create_app(feeds, static, token=TOKEN), base_url="https://testserver")
    response = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Forwarded-Proto": "http"},
        {"Forwarded": "for=192.0.2.60;proto=http"},
        {"X-Forwarded-Ssl": "off"},
        {"Origin": "http://bore.pub:20000"},
        {"Referer": "http://bore.pub:20000/"},
    ],
)
def test_plain_http_has_no_secure_flag(dirs, headers):
    client = make_client(dirs, TOKEN)
    response = client.get(f"/?token={TOKEN}", headers=headers, follow_redirects=False)
    assert response.status_code == 303
    assert "Secure" not in response.headers["set-cookie"]
