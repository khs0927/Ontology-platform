from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import ipaddress
import json
import os
from typing import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


PUBLIC_PATHS = frozenset({"/health"})
LOCAL_CLIENT_NAMES = frozenset({"localhost", "testclient"})


@dataclass(frozen=True)
class BearerPrincipal:
    token: str = field(repr=False)
    scopes: frozenset[str]
    name: str = "configured-token"


@dataclass(frozen=True)
class ApiAuthConfig:
    mode: str
    principals: tuple[BearerPrincipal, ...] = ()

    @classmethod
    def from_env(cls) -> "ApiAuthConfig":
        mode = os.getenv("SION_API_AUTH_MODE", "local").strip().lower()
        if mode not in {"local", "token"}:
            raise ValueError("SION_API_AUTH_MODE must be 'local' or 'token'")

        raw = os.getenv("SION_API_TOKENS_JSON", "").strip()
        principals: list[BearerPrincipal] = []
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("SION_API_TOKENS_JSON must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("SION_API_TOKENS_JSON must be an object mapping bearer tokens to scope arrays")
            for token, scopes in payload.items():
                if not isinstance(token, str) or not token:
                    raise ValueError("SION_API_TOKENS_JSON contains an empty or invalid token")
                if not isinstance(scopes, list) or not scopes or not all(isinstance(scope, str) and scope for scope in scopes):
                    raise ValueError("each configured bearer token must have a non-empty array of scopes")
                principals.append(
                    BearerPrincipal(
                        token=token,
                        scopes=frozenset(scopes),
                    )
                )

        if mode == "token" and not principals:
            raise ValueError("SION_API_AUTH_MODE=token requires SION_API_TOKENS_JSON")
        return cls(mode=mode, principals=tuple(principals))


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status_code: int = 200
    required_scope: str | None = None
    reason: str | None = None


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().lower()
    if normalized in LOCAL_CLIENT_NAMES:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def required_scope(method: str, path: str) -> str | None:
    method = method.upper()
    if method == "OPTIONS" or path in PUBLIC_PATHS:
        return None
    if not path.startswith("/api/v1/"):
        return "__deny__"
    if path.startswith("/api/v1/aec/"):
        return "read:aec"
    if path == "/api/v1/graph" or path.startswith("/api/v1/vector/"):
        return "read:graph"
    if path.startswith("/api/v1/schema/") or path.startswith("/api/v1/bootstrap/"):
        return "read:schema"
    if method == "GET" and (
        path.startswith("/api/v1/entities")
        or path.startswith("/api/v1/relations")
        or path.startswith("/api/v1/evidence")
        or path.startswith("/api/v1/artifacts")
    ):
        return "read:knowledge"
    if method == "POST" and (
        path.startswith("/api/v1/entities")
        or path.startswith("/api/v1/relations")
        or path.startswith("/api/v1/evidence")
        or path.startswith("/api/v1/artifacts")
        or path.startswith("/api/v1/embeddings")
    ):
        return "write:knowledge"
    return "__deny__"


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    token = value[len(prefix):].strip()
    return token or None


def _match_principal(token: str, principals: Iterable[BearerPrincipal]) -> BearerPrincipal | None:
    for principal in principals:
        if hmac.compare_digest(token, principal.token):
            return principal
    return None


def authorize_request(request: Request, config: ApiAuthConfig) -> AuthDecision:
    scope = required_scope(request.method, request.url.path)
    if scope is None:
        return AuthDecision(True)
    if scope == "__deny__":
        return AuthDecision(False, 403, reason="route is not exposed by the API firewall")

    if config.mode == "local":
        if _is_loopback(request.client.host if request.client else None):
            return AuthDecision(True, required_scope=scope)
        return AuthDecision(
            False,
            403,
            required_scope=scope,
            reason="remote API access is disabled in local auth mode",
        )

    token = _bearer_token(request)
    if token is None:
        return AuthDecision(False, 401, required_scope=scope, reason="bearer token required")
    principal = _match_principal(token, config.principals)
    if principal is None:
        return AuthDecision(False, 401, required_scope=scope, reason="invalid bearer token")
    if "*" not in principal.scopes and scope not in principal.scopes:
        return AuthDecision(False, 403, required_scope=scope, reason=f"missing scope: {scope}")
    return AuthDecision(True, required_scope=scope)


def install_auth_firewall(app: FastAPI, config: ApiAuthConfig) -> None:
    app.state.auth_config = config

    @app.middleware("http")
    async def sion_auth_firewall(request: Request, call_next):
        decision = authorize_request(request, config)
        if decision.allowed:
            return await call_next(request)
        headers = {"WWW-Authenticate": "Bearer"} if decision.status_code == 401 else None
        return JSONResponse(
            status_code=decision.status_code,
            content={
                "detail": decision.reason,
                "required_scope": decision.required_scope,
                "auth_mode": config.mode,
            },
            headers=headers,
        )
