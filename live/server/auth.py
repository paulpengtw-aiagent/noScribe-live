"""Optional token gate for the viewer, for exposing it through a tunnel.

Enabled by ``python -m server --token`` (or the LIVE_TOKEN variable). Every HTTP path needs the
token: ``?token=...`` once (it sets a cookie and redirects to the same path without the token), then
the cookie. ``Authorization: Bearer <token>`` works too, for curl. The token is never logged.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE_NAME = "nslive_token"
COOKIE_MAX_AGE_S = 7 * 24 * 3600

LOCKED_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>noScribe Live</title></head>
<body style="font:16px system-ui,sans-serif;margin:3rem;color:#222">
<p>noScribe Live: open the link with ?token=&hellip;</p>
</body>
</html>
"""


def _first_value(header: str) -> str:
    """First element of a comma-separated header, trimmed and lowercased."""
    return header.split(",")[0].strip().lower()


def _forwarded_proto(header: str) -> str:
    """The ``proto=`` parameter of the first element of a RFC 7239 ``Forwarded`` header, or ""."""
    for pair in header.split(",")[0].split(";"):
        key, _, value = pair.partition("=")
        if key.strip().lower() == "proto":
            return value.strip().strip('"').lower()
    return ""


def _is_https(request: Request) -> bool:
    """True when the viewer was reached over https, directly or through a proxy that says so.

    Plain-HTTP access (the bore tunnel) sends none of these, so its cookie has no Secure flag.
    """
    headers = request.headers
    if request.url.scheme == "https":
        return True
    if _first_value(headers.get("x-forwarded-proto", "")) == "https":
        return True
    if _forwarded_proto(headers.get("forwarded", "")) == "https":
        return True
    if _first_value(headers.get("x-forwarded-ssl", "")) == "on":
        return True
    # Last resort: the browser's own Origin or Referer names an https page.
    return any(headers.get(name, "").lower().startswith("https://") for name in ("origin", "referer"))


class TokenGate:
    """ASGI middleware that refuses every HTTP request without the token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _matches(self, supplied: str | None) -> bool:
        # compare_digest on bytes: str arguments must be ASCII, bytes always work.
        return supplied is not None and hmac.compare_digest(supplied.encode("utf-8"), self._token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":   # lifespan and anything else pass through
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        query_token = request.query_params.get("token")
        if self._matches(query_token):
            rest = [(key, value) for key, value in request.query_params.multi_items() if key != "token"]
            location = request.url.path + (f"?{urlencode(rest)}" if rest else "")
            response = RedirectResponse(location, status_code=303)
            response.set_cookie(
                COOKIE_NAME, query_token, max_age=COOKIE_MAX_AGE_S, path="/",
                httponly=True, samesite="lax", secure=_is_https(request),
            )
            await response(scope, receive, send)
            return

        authorization = request.headers.get("authorization", "")
        bearer = authorization[len("Bearer "):] if authorization.startswith("Bearer ") else None
        if self._matches(request.cookies.get(COOKIE_NAME)) or self._matches(bearer):
            await self.app(scope, receive, send)
            return

        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
        else:
            response = HTMLResponse(LOCKED_HTML, status_code=401)
        await response(scope, receive, send)
