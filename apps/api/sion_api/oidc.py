"""OIDC / JWT bearer verification for hosted (SaaS) deployments.

Static tokens (``SION_API_TOKENS_JSON``) stay the default for self-hosted installs. A hosted
deployment puts an identity provider in front instead (Supabase Auth by default; any OIDC
issuer that publishes a JWKS works) and the API verifies its access tokens locally:

* signature against the issuer's JWKS (asymmetric algorithms only; ``none`` and HMAC are refused),
* ``iss``, ``aud``, ``exp``/``nbf`` (with a small leeway) and a required ``sub``,
* scopes and the project allowlist read from configurable claims, fail-closed.

A verified token becomes a ``Principal(kind="user")``. Users never get the ``*`` scope from a
claim, and a token without a project claim sees no projects. Granting projects is the job of
the identity provider (for Supabase: ``app_metadata``, which only the service role can write).

Environment
-----------
``SION_OIDC_ISSUER``          issuer URL, e.g. ``https://<ref>.supabase.co/auth/v1`` (enables OIDC)
``SION_OIDC_AUDIENCE``        expected ``aud`` (default ``authenticated``, Supabase's value)
``SION_OIDC_JWKS_URL``        default ``<issuer>/.well-known/jwks.json``
``SION_OIDC_ALGORITHMS``      comma list, default ``ES256,RS256,EdDSA``
``SION_OIDC_DEFAULT_SCOPES``  scopes every signed-in user gets (default ``read:knowledge``)
``SION_OIDC_SCOPES_CLAIM``    dotted claim path with extra scopes (default ``app_metadata.sion_scopes``)
``SION_OIDC_PROJECTS_CLAIM``  dotted claim path with project ids (default ``app_metadata.sion_projects``)
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from sion_core.optional import require

ASYMMETRIC = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"})
DEFAULT_ALGORITHMS = ("ES256", "RS256", "EdDSA")
LEEWAY_SECONDS = 30
JWKS_TTL_SECONDS = 600


class OidcError(ValueError):
    """The token is not acceptable. The message never contains the token."""


@dataclass(frozen=True)
class OidcClaims:
    subject: str
    scopes: frozenset[str]
    projects: frozenset[str] | None
    email: str | None = None


def _claim(claims: dict[str, Any], path: str) -> Any:
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    if isinstance(value, (list, tuple)):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


@dataclass
class OidcVerifier:
    issuer: str
    audience: str = "authenticated"
    jwks_url: str = ""
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS
    default_scopes: frozenset[str] = frozenset({"read:knowledge"})
    scopes_claim: str = "app_metadata.sion_scopes"
    projects_claim: str = "app_metadata.sion_projects"
    # Injected in tests: returns the signing key for an unverified JWT header.
    key_resolver: Callable[[str], Any] | None = None
    _client: Any = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.issuer = self.issuer.rstrip("/")
        if not self.issuer.startswith("https://") and not self.issuer.startswith("http://localhost"):
            raise RuntimeError("SION_OIDC_ISSUER must be an https URL")
        if not self.jwks_url:
            self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        bad = [alg for alg in self.algorithms if alg not in ASYMMETRIC]
        if bad or not self.algorithms:
            raise RuntimeError("SION_OIDC_ALGORITHMS must list asymmetric algorithms only")
        if "*" in self.default_scopes:
            raise RuntimeError("SION_OIDC_DEFAULT_SCOPES must not grant '*'")

    @classmethod
    def from_env(cls) -> "OidcVerifier | None":
        issuer = os.getenv("SION_OIDC_ISSUER", "").strip()
        if not issuer:
            return None
        algorithms = tuple(_string_list(os.getenv("SION_OIDC_ALGORITHMS", ""))) or DEFAULT_ALGORITHMS
        defaults = os.getenv("SION_OIDC_DEFAULT_SCOPES")
        return cls(
            issuer=issuer,
            audience=os.getenv("SION_OIDC_AUDIENCE", "authenticated").strip() or "authenticated",
            jwks_url=os.getenv("SION_OIDC_JWKS_URL", "").strip(),
            algorithms=algorithms,
            default_scopes=frozenset(_string_list(defaults)) if defaults is not None else frozenset({"read:knowledge"}),
            scopes_claim=os.getenv("SION_OIDC_SCOPES_CLAIM", "app_metadata.sion_scopes").strip(),
            projects_claim=os.getenv("SION_OIDC_PROJECTS_CLAIM", "app_metadata.sion_projects").strip(),
        )

    @staticmethod
    def looks_like_jwt(token: str) -> bool:
        return token.count(".") == 2 and len(token) < 16_384

    def _signing_key(self, token: str) -> Any:
        if self.key_resolver is not None:
            return self.key_resolver(token)
        jwt = require("jwt", "saas")
        with self._lock:
            if self._client is None:
                self._client = jwt.PyJWKClient(self.jwks_url, cache_keys=True, lifespan=JWKS_TTL_SECONDS, timeout=5)
        return self._client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> OidcClaims:
        jwt = require("jwt", "saas")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise OidcError("malformed token") from None
        if header.get("alg") not in self.algorithms:
            raise OidcError("token algorithm not allowed")
        try:
            key = self._signing_key(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"token rejected: {type(exc).__name__}") from None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OidcError("token has no subject")

        from .auth import normalize_project_id  # local import: auth imports this module

        extra = {scope for scope in _string_list(_claim(claims, self.scopes_claim)) if scope != "*"}
        raw_projects = _string_list(_claim(claims, self.projects_claim))
        projects: frozenset[str] | None
        if "*" in raw_projects:
            projects = None
        else:
            projects = frozenset(p for p in (normalize_project_id(v) for v in raw_projects) if p is not None)
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        return OidcClaims(subject=subject, scopes=frozenset(self.default_scopes | extra), projects=projects, email=email)

