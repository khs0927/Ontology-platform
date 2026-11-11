"""Opt-in read-only process for a mobile copy of the operational API.

``AEC_API_READ_ONLY`` unset or false leaves the PC runtime unchanged.
``AEC_API_READ_ONLY=1`` rejects mutating routes, marks responses as non-canonical,
and refuses to start without a bearer token and a non-owner database URL.

The entrypoint ``python -m aec_intelligence.operational.readonly`` is what the
mobile compose file runs. The PC image command stays ``uvicorn`` and does not
come through here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import unquote, urlsplit

from .auth import api_token_from_env
from .config import env_flag

READ_ONLY_ENV = "AEC_API_READ_ONLY"
# POST routes that compute an answer and do not persist. Everything else that is
# not GET/HEAD/OPTIONS is rejected before the handler or the database.
READ_ONLY_POST_PATHS = frozenset({"/v1/search", "/v1/ask"})
PLACEHOLDER_PASSWORDS = frozenset({"change-me", "replace-with-password"})
PLACEHOLDER_TOKENS = frozenset({"replace-with-token", "change-me", "changeme"})
MIN_TOKEN_LENGTH = 16
# The writer stack publishes Postgres on this loopback port and names the
# container/service aec-db (compose service ``db``). The read-only process must
# not attach to either by accident.
PC_DATABASE_PORT = 55432
PC_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PC_DATABASE_NAMES = frozenset({"aec-db", "db"})
OWNER_ROLES = frozenset({"aec"})

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def read_only_enabled() -> bool:
    return env_flag(READ_ONLY_ENV)


def assert_read_only_config(dsn: str) -> None:
    """Fail closed before a read-only process accepts traffic.

    Error text never includes the URL, the password, or the token.
    """
    token = api_token_from_env()
    if token is None or token.lower() in PLACEHOLDER_TOKENS or len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError("AEC_API_READ_ONLY=1 requires a non-placeholder AEC_API_TOKEN of at least 16 characters")
    parts = urlsplit((dsn or "").strip())
    if parts.scheme not in {"postgresql", "postgres"} or not parts.hostname:
        raise RuntimeError("AEC_API_READ_ONLY=1 requires a postgresql URL")
    user = unquote(parts.username or "").lower()
    password = unquote(parts.password or "")
    host = (parts.hostname or "").lower()
    port = parts.port or 5432
    if not user or user in OWNER_ROLES:
        raise RuntimeError("AEC_API_READ_ONLY=1 requires the aec_reader role, not the database owner")
    if not password or password in PLACEHOLDER_PASSWORDS:
        raise RuntimeError("AEC_API_READ_ONLY=1 refuses a placeholder database password")
    if host in PC_DATABASE_NAMES or (host in PC_DATABASE_HOSTS and port == PC_DATABASE_PORT):
        raise RuntimeError("AEC_API_READ_ONLY=1 refuses the PC database address")


def _marker_headers(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    return [*headers, (b"x-aec-read-only", b"1"), (b"x-aec-canonical", b"0")]


class ReadOnlyMiddleware:
    """Reject writes. Search and ask stay, and ask will not call a model."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        allowed = method in {"GET", "HEAD", "OPTIONS"} or (method == "POST" and path in READ_ONLY_POST_PATHS)
        if not allowed:
            body = json.dumps(
                {"detail": "This deployment is read-only", "read_only": True, "canonical": False}
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": _marker_headers(
                        [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"allow", b"GET, HEAD, OPTIONS"),
                            (b"cache-control", b"no-store"),
                        ]
                    ),
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_marked(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": _marker_headers(list(message.get("headers") or []))}
            await send(message)

        await self.app(scope, receive, send_marked)


def main() -> None:
    """Process entry for the mobile compose file. Does not return on success."""
    os.environ[READ_ONLY_ENV] = "1"
    try:
        assert_read_only_config(os.getenv("AEC_DATABASE_URL", ""))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "aec_intelligence.operational.api:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )


if __name__ == "__main__":
    main()
