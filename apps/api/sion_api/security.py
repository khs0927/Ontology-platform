from __future__ import annotations

import hmac
import ipaddress

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

bearer_scheme = HTTPBearer(auto_error=False)


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "::1":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_startup_settings(settings: Settings) -> None:
    if settings.environment == "production":
        if not settings.local_api_token:
            raise RuntimeError("SION_LOCAL_API_TOKEN must be set in production")
        if not settings.database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("SION_DATABASE_URL must use postgresql+psycopg in production")
        if settings.auto_create_schema:
            raise RuntimeError("SION_AUTO_CREATE_SCHEMA must be false in production")
    elif not is_loopback_host(settings.api_host) and not settings.local_api_token:
        raise RuntimeError(
            "SION_LOCAL_API_TOKEN must be set when SION_API_HOST is non-loopback"
        )


def require_local_bearer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = bearer_scheme,
) -> None:
    settings: Settings = request.app.state.settings
    if settings.local_api_token is None:
        if not is_loopback_host(settings.api_host):
            raise HTTPException(status_code=403, detail="local API token is not configured")
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(credentials.credentials, settings.local_api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
