"""Cloud-ops readiness: liveness/readiness probes and structured access logging.

* ``GET /health/live``  - process is up; never touches the database.
* ``GET /health/ready`` - read-only ``SELECT 1`` against the configured database.
  The response carries only coarse status values (no DSN, host, user, driver error text).
* ``AccessLogMiddleware`` - one JSON line per HTTP request on the ``sion_api.access`` logger.
  It records method, route path (without the query string), status, duration and a request id.
  Request headers, query strings and bodies are never logged, so ``Authorization`` bearer
  tokens, cookies and PII in query parameters cannot leak into logs.

See ``docs/ops/CLOUD-OPS.ko.md`` for the runbook.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

ACCESS_LOGGER_NAME = "sion_api.access"
REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Header names that must never be emitted by any ops log helper.
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]+")
_MAX_PATH = 256


def _access_log_enabled() -> bool:
    value = os.getenv("SION_API_ACCESS_LOG", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with credential-bearing values replaced."""

    return {
        name: ("[REDACTED]" if name.lower() in SENSITIVE_HEADERS else _BEARER.sub(r"\1 [REDACTED]", value))
        for name, value in headers.items()
    }


def _safe_path(path: str) -> str:
    # Paths are logged without the query string; strip credential-looking fragments defensively.
    cleaned = _BEARER.sub(r"\1 [REDACTED]", path)
    return cleaned if len(cleaned) <= _MAX_PATH else cleaned[:_MAX_PATH] + "..."


class AccessLogMiddleware:
    """Pure ASGI middleware emitting one structured JSON line per HTTP request."""

    def __init__(self, app, logger: logging.Logger | None = None) -> None:
        self.app = app
        self.logger = logger or logging.getLogger(ACCESS_LOGGER_NAME)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers") or ():
            if name.lower() == REQUEST_ID_HEADER.encode():
                candidate = value.decode("latin-1")
                if _SAFE_REQUEST_ID.match(candidate):
                    incoming = candidate
                break
        request_id = incoming or uuid.uuid4().hex
        status_holder = {"status": 500}
        started = time.perf_counter()

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if _access_log_enabled():
                record = {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": scope.get("method", ""),
                    "path": _safe_path(scope.get("path", "")),
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
                self.logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


def register(app: FastAPI, engine: Engine, version: str) -> None:
    """Attach liveness/readiness probes. Both are unauthenticated and secret-free."""

    @app.get("/health/live", tags=["ops"])
    def health_live():
        return {"status": "ok", "service": "sion-ontology-api", "version": version}

    @app.get("/health/ready", tags=["ops"])
    def health_ready():
        checks = {"database": "ok"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar()
                connection.rollback()
        except Exception:  # noqa: BLE001 - never echo driver errors (may contain DSN/host)
            logging.getLogger("sion_api.ops").warning("readiness: database check failed")
            checks["database"] = "unavailable"
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "version": version, "checks": checks},
            )
        return {"status": "ok", "version": version, "database": engine.dialect.name, "checks": checks}
