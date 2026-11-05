from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

VALID_MODES = frozenset({"local-only", "bearer", "local-or-bearer"})
# Legacy project ACL form: ``project:<uuid>`` entries inside a token's scope list.
PROJECT_SCOPE_PREFIX = "project:"

# Scopes are deliberately disjoint: ``write:*`` does not imply ``read:*``. A reviewer
# token that reads candidates and records decisions needs both scopes (or ``*``).
KNOWN_SCOPES = frozenset({"read:knowledge", "write:knowledge", "read:aec", "*"})


@dataclass(frozen=True)
class Principal:
    """The authorized caller, stored on ``request.state.sion_principal``.

    It never carries the bearer token itself, so handlers may inspect it freely.
    ``projects`` is ``None`` for an unrestricted caller (trusted local access or a
    token without a project allowlist); otherwise only those project ids are visible.
    """

    kind: str  # "local" or "bearer"
    scopes: frozenset[str]
    projects: frozenset[str] | None = None

    def can_access_project(self, project_id: object) -> bool:
        if self.projects is None:
            return True
        normalized = normalize_project_id(project_id)
        return normalized is not None and normalized in self.projects


LOCAL_PRINCIPAL = Principal(kind="local", scopes=frozenset({"*"}))


def normalize_project_id(value: object) -> str | None:
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _parse_grant(grant: object) -> tuple[frozenset[str], frozenset[str] | None]:
    """Accept the legacy ``["scope", ...]`` form or ``{"scopes": [...], "projects": [...]}``."""
    projects: frozenset[str] | None = None
    if isinstance(grant, dict):
        if set(grant) - {"scopes", "projects"}:
            raise RuntimeError("SION API token grants accept only 'scopes' and 'projects' keys")
        scopes = grant.get("scopes")
        if "projects" in grant:
            raw_projects = grant["projects"]
            if not isinstance(raw_projects, list) or not raw_projects:
                raise RuntimeError("SION API token 'projects' must be a non-empty list of project UUIDs")
            normalized = [normalize_project_id(item) for item in raw_projects]
            if any(item is None for item in normalized):
                raise RuntimeError("SION API token 'projects' must contain only project UUID strings")
            projects = frozenset(item for item in normalized if item is not None)
    else:
        scopes = grant
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) and scope.strip() for scope in scopes)
    ):
        raise RuntimeError("each SION API token must map to a non-empty list of scopes")
    return frozenset(scope.strip() for scope in scopes), projects


@dataclass(frozen=True)
class AuthPolicy:
    """Small, dependency-free, provider-neutral API authorization policy.

    Default behavior is deliberately local-only. Remote deployments must opt in
    to bearer auth and provide an explicit token -> scopes map (optionally with a
    per-token project allowlist). An OIDC/OAuth front door can mint or map tokens
    onto this policy without changing route code.
    """

    mode: str
    token_scopes: tuple[tuple[str, frozenset[str]], ...] = ()
    trusted_origins: tuple[str, ...] = ()
    # Optional per-token project ACL: token -> allowed project ids. Tokens absent here
    # are unrestricted (backward compatible with the plain token -> scopes map).
    token_projects: tuple[tuple[str, frozenset[str]], ...] = ()

    @classmethod
    def from_env(cls) -> "AuthPolicy":
        mode = os.getenv("SION_API_AUTH_MODE", "local-only").strip().lower()
        if mode not in VALID_MODES:
            raise RuntimeError("SION_API_AUTH_MODE must be one of: local-only, bearer, local-or-bearer")

        raw = os.getenv("SION_API_TOKENS_JSON", "").strip()
        token_scopes: list[tuple[str, frozenset[str]]] = []
        token_projects: list[tuple[str, frozenset[str]]] = []
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # Do not chain the decode error: it carries the raw (secret) document.
                raise RuntimeError("SION_API_TOKENS_JSON must be valid JSON") from None
            if not isinstance(parsed, dict):
                raise RuntimeError("SION_API_TOKENS_JSON must be an object mapping token to scopes")
            for token, grant in parsed.items():
                if not isinstance(token, str) or len(token) < 16:
                    raise RuntimeError("SION API bearer tokens must be strings of at least 16 characters")
                scopes, projects = _parse_grant(grant)
                token_scopes.append((token, scopes))
                if projects is not None:
                    token_projects.append((token, projects))

        if mode in {"bearer", "local-or-bearer"} and not token_scopes:
            raise RuntimeError("SION_API_TOKENS_JSON is required when bearer authentication is enabled")
        return cls(mode=mode, token_scopes=tuple(token_scopes), token_projects=tuple(token_projects))

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

    def _principal_for_authorization(self, authorization: str | None) -> Principal | None:
        if not authorization:
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            return None
        presented = token.encode("utf-8")
        scopes = _lookup(self.token_scopes, presented)
        if scopes is None:
            return None
        projects = _lookup(self.token_projects, presented)
        if "*" not in scopes:
            # ``project:<uuid>`` scope entries also restrict the token. Malformed entries fail
            # closed: the token stays restricted but the entry grants nothing.
            entries = [s[len(PROJECT_SCOPE_PREFIX):] for s in scopes if s.startswith(PROJECT_SCOPE_PREFIX)]
            if entries:
                from_scopes = frozenset(p for p in (normalize_project_id(e) for e in entries) if p is not None)
                projects = from_scopes if projects is None else projects & from_scopes
        return Principal(kind="bearer", scopes=scopes, projects=projects)

    def _matched_token(self, authorization: str | None) -> str | None:
        """The configured token the header authenticates as (never returned to clients)."""
        if not authorization:
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            return None
        presented = token.encode("utf-8")
        found: str | None = None
        for expected, _scopes in self.token_scopes:
            if hmac.compare_digest(presented, expected.encode("utf-8")) and found is None:
                found = expected
        return found

    def _scopes_for_authorization(self, authorization: str | None) -> frozenset[str] | None:
        principal = self._principal_for_authorization(authorization)
        return None if principal is None else principal.scopes

    def authorize(self, request: Request, scope: str) -> Principal:
        """Authenticate the request and require ``scope``.

        Error details never include the presented credential. The resulting
        principal is stored on ``request.state.sion_principal`` for project ACL checks.
        """
        is_local = self._trusted_local_request(request)
        if self.mode == "local-only":
            if is_local:
                return _remember(request, LOCAL_PRINCIPAL)
            raise HTTPException(
                status_code=403,
                detail="remote API access is disabled; configure bearer authentication",
            )

        if self.mode == "local-or-bearer" and is_local:
            return _remember(request, LOCAL_PRINCIPAL)

        principal = self._principal_for_authorization(request.headers.get("Authorization"))
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="valid bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if "*" not in principal.scopes and scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"missing required scope: {scope}")
        return _remember(request, principal)


    def allowed_projects(self, request: Request) -> frozenset[str] | None:
        """Project ACL for an already authorized request; ``None`` means unrestricted."""
        principal = getattr(request.state, "sion_principal", None)
        if isinstance(principal, Principal):
            return principal.projects
        if self.mode == "local-only":
            return None
        if self.mode == "local-or-bearer" and self._trusted_local_request(request):
            return None
        principal = self._principal_for_authorization(request.headers.get("Authorization"))
        return frozenset() if principal is None else principal.projects

    def client_key(self, request: Request) -> str:
        """Stable, non-secret identity for per-client throttling.

        Derived from the authenticated identity, never raw header text, so re-spelling the
        ``Bearer`` scheme cannot mint fresh buckets. Trusted local requests key on the peer
        address; bearer requests on a digest of the matched configured token.
        """
        host = "host:" + (request.client.host if request.client else "unknown")
        if self.mode != "bearer" and self._trusted_local_request(request):
            return host
        matched = self._matched_token(request.headers.get("Authorization"))
        if matched is not None:
            return "token:" + hashlib.sha256(matched.encode("utf-8")).hexdigest()[:32]
        return host

def _lookup(entries: Iterable[tuple[str, frozenset[str]]], presented: bytes) -> frozenset[str] | None:
    """Constant-time comparison against every configured token."""
    found: frozenset[str] | None = None
    for expected, values in entries:
        if hmac.compare_digest(presented, expected.encode("utf-8")) and found is None:
            found = values
    return found


def _remember(request: Request, principal: Principal) -> Principal:
    request.state.sion_principal = principal
    return principal


def require_scope(policy: AuthPolicy, scope: str, *, project_scoped: bool = False) -> Callable[[Request], None]:
    """FastAPI dependency requiring ``scope``.

    A token restricted to a project allowlist may only reach routes declared
    ``project_scoped`` (routes that apply the project ACL themselves through
    :func:`require_project_access` / :func:`allowed_projects`). Every other route
    could return cross-project data, so restricted tokens fail closed there.
    """

    def dependency(request: Request) -> None:
        principal = policy.authorize(request, scope)
        if principal.projects is not None and not project_scoped:
            raise HTTPException(
                status_code=403,
                detail="project-restricted token cannot access cross-project routes",
            )

    # Introspected by the route-coverage test (tests/test_api_scopes.py).
    dependency.required_scope = scope  # type: ignore[attr-defined]
    dependency.project_scoped = project_scoped  # type: ignore[attr-defined]
    dependency.policy = policy  # type: ignore[attr-defined]
    return dependency


def project_scoped(dependency: Callable[[Request], None]) -> Callable[[Request], None]:
    """Derive a project-scoped variant of a :func:`require_scope` dependency."""
    if not hasattr(dependency, "policy"):
        return dependency  # not produced by require_scope; nothing to relax
    return require_scope(
        dependency.policy,  # type: ignore[attr-defined]
        dependency.required_scope,  # type: ignore[attr-defined]
        project_scoped=True,
    )


def current_principal(request: Request) -> Principal:
    """The principal recorded by a scope dependency; fails closed if none ran."""
    principal = getattr(request.state, "sion_principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=403, detail="request was not authorized")
    return principal


def require_project_access(request: Request, project_id: object) -> None:
    """Project ACL gate. Call before reading or writing project-scoped data.

    Denials answer 404 so a restricted token cannot probe for other projects.
    """
    if not current_principal(request).can_access_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")


def allowed_projects(request: Request) -> frozenset[str] | None:
    """Project ids visible to the caller, or ``None`` when unrestricted."""
    return current_principal(request).projects
