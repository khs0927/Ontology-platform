"""Opt-in bearer-token authentication for the operational REST API.

``AEC_API_TOKEN`` unset or blank → token-free access for trusted loopback requests only.
``AEC_API_TOKEN`` set → every request needs ``Authorization: Bearer <token>`` except the liveness
probe and the static dashboard shell (``/healthz``, ``/``, ``/dashboard``, ``/static/*``), which hold no
data. The dashboard asks for the token and sends it on its API calls. CORS preflight (``OPTIONS``)
is passed through so the CORS middleware can answer it.

power-cad-mcp sends ``POWERCAD_ONTOLOGY_TOKEN`` in exactly this header format, so set both variables
to the same value.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

TOKEN_ENV = "AEC_API_TOKEN"
OPEN_PATHS = frozenset({"/healthz", "/", "/dashboard"})
OPEN_PREFIXES = ("/static/",)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def api_token_from_env(value: str | None = None) -> str | None:
    raw = os.getenv(TOKEN_ENV) if value is None else value
    token = (raw or "").strip()
    return token or None


def _bearer(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, raw in headers:
        if name.lower() == b"authorization":
            scheme, _, credentials = raw.decode("latin-1").strip().partition(" ")
            if scheme.lower() == "bearer" and credentials.strip():
                return credentials.strip()
            return None
    return None


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)


class BearerTokenMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware) so streaming/background tasks are unaffected."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware needs a non-empty token")
        self.app = app
        self._expected = token.encode("utf-8")

    def _authorized(self, scope: Scope) -> bool:
        presented = _bearer(scope.get("headers") or [])
        if presented is None:
            return False
        return hmac.compare_digest(presented.encode("utf-8"), self._expected)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "websocket":
            # No websocket routes today; any future one is covered by the same token instead of open.
            if self._authorized(scope):
                await self.app(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        if kind != "http" or scope.get("method") == "OPTIONS" or is_open_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "Missing or invalid bearer token"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b'Bearer realm="aec-intelligence"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class LocalOnlyMiddleware:
    """Token-free API access requires a loopback peer and a trusted browser target."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed_origins = tuple(allowed_origins or ())

    def _authorized(self, scope: Scope) -> bool:
        client = scope.get("client")
        if not client:
            return False
        try:
            if not ipaddress.ip_address(client[0]).is_loopback:
                return False
        except ValueError:
            return False
        headers = scope.get("headers") or []
        hosts = [v.decode("latin-1") for k, v in headers if k.lower() == b"host"]
        origins = [v.decode("latin-1") for k, v in headers if k.lower() == b"origin"]
        if len(hosts) != 1 or len(origins) > 1:
            return False
        try:
            host = urlsplit("//" + hosts[0])
            host.port
            if host.username or host.password or host.path or host.query or host.fragment:
                return False
            if host.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
        except ValueError:
            return False
        if origins:
            return origins[0] == f"{scope.get('scheme', 'http')}://{hosts[0]}" or origins[0] in self.allowed_origins
        return not any(k.lower() == b"sec-fetch-site" and v == b"cross-site" for k, v in headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or is_open_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b'{"detail":"Token-free API access is restricted to trusted local requests"}'
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]})
        await send({"type": "http.response.body", "body": body})
