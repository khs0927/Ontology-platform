"""Read-only, fail-closed Sion Ontology API operational preflight.

All requests use GET. Nothing is imported or approved, and this tool never
performs a GraphRAG query (which may incur model costs).

Requires only the Python standard library. Example:
  SION_AUDIT_BEARER_TOKEN=... python scripts/audit_ontology_readonly.py \
      --base-url https://sion-staging.example.net
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 65536
CHECK_PATHS = {
    "health": "/health",
    "readiness": "/health/ready",
    "graphrag": "/api/v1/graphrag/status",
    "storage": "/api/v1/storage/status",
    "aec": "/api/v1/aec/status",
}
PUBLIC_CHECKS = frozenset({"health", "readiness"})


class _NoRedirect(HTTPRedirectHandler):
    """Never forward a bearer token (or make an extra request) via redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def validate_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("base URL must be an absolute HTTPS URL or localhost HTTP URL")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("base URL must not contain credentials, path, query or fragment")
    if parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("non-loopback HTTP is refused; use HTTPS")
    if any(x in value for x in ("\r", "\n", "\t")):
        raise ValueError("invalid URL whitespace")
    return value.rstrip("/")


def _fetch(
    base_url: str,
    path: str,
    token: str | None,
    timeout: float,
    open_request: Callable[..., Any],
) -> tuple[str, dict[str, Any] | None]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base_url + path, headers=headers, method="GET")
    try:
        with open_request(request, timeout=timeout) as response:
            # Refuse oversized responses, including responses without Content-Length.
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                return "oversized_response", None
            data = json.loads(payload)
            return ("ok", data) if isinstance(data, dict) else ("invalid_json", None)
    except HTTPError as exc:
        if exc.code == 404:
            return "not_implemented", None
        if exc.code in (401, 403):
            return "unauthorized", None
        if exc.code == 503:
            return "unavailable", None
        return "http_error", None
    except (OSError, URLError, TimeoutError):
        return "unreachable", None
    except (ValueError, UnicodeDecodeError):
        return "invalid_json", None


def audit(
    base_url: str,
    *,
    token: str | None = None,
    timeout: float = 6.0,
    open_request: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return sanitized statuses. Never return URLs, model names, paths or credentials."""
    base_url = validate_base_url(base_url)
    if timeout <= 0 or timeout > 30:
        raise ValueError("timeout must be between 0 and 30 seconds")
    if open_request is None:
        opener = build_opener(_NoRedirect())
        open_request = opener.open

    checks: dict[str, dict[str, Any]] = {}
    for name, path in CHECK_PATHS.items():
        if name not in PUBLIC_CHECKS and not token:
            checks[name] = {"result": "skipped_no_token"}
            continue
        status, payload = _fetch(base_url, path, None if name in PUBLIC_CHECKS else token, timeout, open_request)
        check: dict[str, Any] = {"result": status}
        if status == "ok" and payload is not None:
            if name == "health":
                check["responding"] = payload.get("status") == "ok"
            elif name == "readiness":
                check["database_ready"] = payload.get("checks", {}).get("database") == "ok" if isinstance(payload.get("checks"), dict) else False
            elif name == "graphrag":
                check["configured"] = payload.get("configured") is True
                check["answers_enabled"] = payload.get("answers_enabled") is True
                check["canonical"] = payload.get("canonical") is True
            elif name == "storage":
                check["enabled"] = payload.get("status") == "ok"
            elif name == "aec":
                check["configured"] = payload.get("configured") is True
        checks[name] = check

    # This tool deliberately does not execute ingest, vector search, a write,
    # a real model call, mobile OAuth or an E2E test. Never label them complete.
    preflight = (
        checks["health"].get("responding") is True
        and checks["readiness"].get("database_ready") is True
        and checks["graphrag"].get("configured") is True
    )
    return {
        "schema": "sion-ontology-readonly-preflight/1",
        "read_only": True,
        "configuration_preflight_passed": preflight,
        "end_to_end_verified": False,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="root HTTPS URL, or HTTP loopback")
    parser.add_argument("--token-env", default="SION_AUDIT_BEARER_TOKEN", help="environment variable with read-scope bearer token")
    parser.add_argument("--timeout", type=float, default=6.0)
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env)
    try:
        result = audit(args.base_url, token=token, timeout=args.timeout)
    except ValueError as exc:
        # Never echo a supplied URL; it might contain credentials by mistake.
        print(json.dumps({"schema": "sion-ontology-readonly-preflight/1", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["configuration_preflight_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
