from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

VALID_MODES = frozenset({"local-only", "bearer", "local-or-bearer"})
PROJECT_SCOPE_PREFIX = "project:"


@dataclass(frozen=True)
class AuthPolicy:
    """Small, dependency-free API authorization policy.

    Default behavior is deliberately local-only. Remote deployments must opt in
    to bearer auth and provide an explicit token -> scopes map.
    """

    mode: str
    token_scopes: tuple[tuple[str, frozenset[str]], ...] = ()
    trusted_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "AuthPolicy":
        mode = os.getenv("SION_API_AUTH_MODE", "local-only").strip().lower()
        if mode not in VALID_MODES:
            raise RuntimeError(
                "SION_API_AUTH_MODE must be one of: local-only, bearer, local-or-bearer"
            )

        raw = os.getenv("SION_API_TOKENS_JSON", "").strip()
        token_scopes: list[tuple[str, frozenset[str]]] = []
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("SION_API_TOKENS_JSON must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise RuntimeError("SION_API_TOKENS_JSON must be an object mapping token to scopes")
            for token, scopes in parsed.items():
                if not isinstance(token, str) or len(token) < 16:
                    raise RuntimeError("SION API bearer tokens must be strings of at least 16 characters")
                if not isinstance(scopes, list) or not scopes or not all(
                    isinstance(scope, str) and scope.strip() for scope in scopes
                ):
                    raise RuntimeError("each SION API token must map to a non-empty list of scopes")
                token_scopes.append((token, frozenset(scope.strip() for scope in scopes)))

        if mode in {"bearer", "local-or-bearer"} and not token_scopes:
            raise RuntimeError(
                "SION_API_TOKENS_JSON is required when bearer authentication is enabled"
            )
        return cls(mode=mode, token_scopes=tuple(token_scopes))

    @staticmethod
    def _is_local(request: Request) -> bool:
        if request.client is None:
            return False
        host = request.client.host
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _trusted_local_request(self, request: Request) -> bool:
        """A loopback peer alone does not establish browser request authority."""
        if not self._is_local(request):
            return False
        hosts = request.headers.getlist("host")
        origins = request.headers.getlist("origin")
        if len(hosts) != 1 or len(origins) > 1:
            return False
        try:
            host = urlsplit("//" + hosts[0])
            if host.username or host.password or host.path or host.query or host.fragment:
                return False
            # Force port validation too; malformed ports must fail closed.
            host.port
            if host.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return False
        except ValueError:
            return False
        if not origins:
            return request.headers.get("sec-fetch-site") != "cross-site"
        same_origin = f"{request.url.scheme}://{hosts[0]}"
        return origins[0] == same_origin or origins[0] in self.trusted_origins

    def _matched_token(self, authorization: str | None) -> tuple[str, frozenset[str]] | None:
        """Return the configured ``(token, scopes)`` entry the header authenticates as."""
        if not authorization:
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            return None
        for expected, scopes in self.token_scopes:
            if hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
                return expected, scopes
        return None

    def _scopes_for_authorization(self, authorization: str | None) -> frozenset[str] | None:
        matched = self._matched_token(authorization)
        return matched[1] if matched else None

    def authorize(self, request: Request, scope: str) -> None:
        is_local = self._trusted_local_request(request)
        if self.mode == "local-only":
            if is_local:
                return
            raise HTTPException(
                status_code=403,
                detail="remote API access is disabled; configure bearer authentication",
            )

        if self.mode == "local-or-bearer" and is_local:
            return

        scopes = self._scopes_for_authorization(request.headers.get("Authorization"))
        if scopes is None:
            raise HTTPException(
                status_code=401,
                detail="valid bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if "*" not in scopes and scope not in scopes:
            raise HTTPException(status_code=403, detail=f"missing required scope: {scope}")

    def allowed_projects(self, request: Request) -> frozenset[str] | None:
        """Project ACL for an already authorized request; ``None`` means unrestricted.

        A bearer token whose scope list contains ``project:<uuid>`` entries is limited
        to those projects. Tokens without project entries, ``*`` tokens and trusted
        local requests stay unrestricted. Malformed project entries fail closed: the
        token remains restricted but the entry grants nothing.
        """
        if self.mode == "local-only":
            return None
        if self.mode == "local-or-bearer" and self._trusted_local_request(request):
            return None
        scopes = self._scopes_for_authorization(request.headers.get("Authorization"))
        if scopes is None:
            return frozenset()
        if "*" in scopes:
            return None
        entries = [scope[len(PROJECT_SCOPE_PREFIX):] for scope in scopes if scope.startswith(PROJECT_SCOPE_PREFIX)]
        if not entries:
            return None
        allowed: set[str] = set()
        for entry in entries:
            try:
                allowed.add(str(uuid.UUID(entry)))
            except ValueError:
                continue
        return frozenset(allowed)

    def client_key(self, request: Request) -> str:
        """Stable, non-secret identity for per-client throttling.

        The key comes from the authenticated identity, never from raw header text, so
        re-spelling the ``Bearer`` scheme or sending arbitrary headers from a trusted
        local peer cannot mint fresh buckets. Trusted local requests key on the peer
        address (mirroring ``authorize``); bearer requests key on a digest of the
        matched configured token.
        """
        host = "host:" + (request.client.host if request.client else "unknown")
        if self.mode != "bearer" and self._trusted_local_request(request):
            return host
        matched = self._matched_token(request.headers.get("Authorization"))
        if matched is not None:
            return "token:" + hashlib.sha256(matched[0].encode("utf-8")).hexdigest()[:32]
        return host


def require_scope(policy: AuthPolicy, scope: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        policy.authorize(request, scope)

    return dependency
