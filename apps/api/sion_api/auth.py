from __future__ import annotations

import hmac
import ipaddress
import json
import os
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request

VALID_MODES = frozenset({"local-only", "bearer", "local-or-bearer"})


@dataclass(frozen=True)
class AuthPolicy:
    """Small, dependency-free API authorization policy.

    Default behavior is deliberately local-only. Remote deployments must opt in
    to bearer auth and provide an explicit token -> scopes map.
    """

    mode: str
    token_scopes: tuple[tuple[str, frozenset[str]], ...] = ()

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
        if host == "testclient":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host.lower() == "localhost"

    def _scopes_for_authorization(self, authorization: str | None) -> frozenset[str] | None:
        if not authorization:
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            return None
        for expected, scopes in self.token_scopes:
            if hmac.compare_digest(token, expected):
                return scopes
        return None

    def authorize(self, request: Request, scope: str) -> None:
        is_local = self._is_local(request)
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


def require_scope(policy: AuthPolicy, scope: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        policy.authorize(request, scope)

    return dependency
