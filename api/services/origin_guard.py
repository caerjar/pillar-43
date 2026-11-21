"""Refuse state-changing requests that a page on another origin sent.

CORS only decides whether a page may READ a response. A cross-origin page can
still make the browser send a POST whose body has no Content-Type (no
preflight), and FastAPI parses that body as JSON, so the handler runs. This
middleware closes that: an unsafe method carrying an ``Origin`` header is
refused unless the origin is the app itself.

An origin is the app itself when any of these holds:
  * it is in the CORS allowlist (the Vite dev and preview servers);
  * the browser says ``Sec-Fetch-Site: same-origin`` (the nginx and Vite
    proxies rewrite ``Host``, so the browser-set header is the reliable
    signal; a page cannot forge it);
  * its host:port equals the request ``Host`` (the desktop shell loads
    ``http://127.0.0.1:<port>`` from this server directly).

Requests with no ``Origin`` (curl, the CLI, server-to-server) pass: they are
not browser-driven. ``Origin: null`` (sandboxed iframes, data: URLs) is
refused. Safe methods are never touched.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://localhost:5173",
    "http://localhost:4173",
]

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_BODY = json.dumps({"detail": "Cross-origin request refused"}).encode()


def origin_allowed(origin: str, host: str, sec_fetch_site: str) -> bool:
    if origin in CORS_ORIGINS:
        return True
    if sec_fetch_site == "same-origin":
        return True
    if origin.startswith(("http://", "https://")) and host:
        return origin.split("://", 1)[1].lower() == host.lower()
    return False


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _UNSAFE:
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope["headers"]
        }
        origin = headers.get("origin")
        if origin is None or origin_allowed(
            origin, headers.get("host", ""), headers.get("sec-fetch-site", "")
        ):
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BODY})
