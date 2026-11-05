"""The OpenAPI schema declares the bearer requirement the auth policy enforces."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sion_api.auth import BEARER_SCHEME, AuthPolicy
from sion_api.main import create_app

TOKEN = "test-only-openapi-token"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _schema(mode: str) -> dict:
    policy = AuthPolicy(mode=mode, token_scopes=((TOKEN, frozenset({"*"})),))
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _operations(schema: dict):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def test_bearer_mode_declares_scheme_and_scopes_on_protected_routes():
    schema = _schema("bearer")
    assert schema["components"]["securitySchemes"][BEARER_SCHEME] == {"type": "http", "scheme": "bearer"}

    ops = {(path, method): op for path, method, op in _operations(schema)}
    entities_get = ops[("/api/v1/entities", "get")]
    assert entities_get["security"] == [{BEARER_SCHEME: []}]
    assert entities_get["x-sion-scopes"] == ["read:knowledge"]
    assert ops[("/api/v1/entities", "post")]["x-sion-scopes"] == ["write:knowledge"]
    assert ops[("/api/v1/aec/status", "get")]["x-sion-scopes"] == ["read:aec"]

    protected = [op for op in ops.values() if "security" in op]
    assert len(protected) > 10
    for op in protected:
        assert op["x-sion-scopes"], op


def test_unprotected_routes_carry_no_security_requirement():
    schema = _schema("bearer")
    health = [op for path, _, op in _operations(schema) if path.startswith("/health")]
    assert health, "expected a public health route"
    assert all("security" not in op for op in health)


def test_local_or_bearer_marks_the_token_optional():
    ops = {(p, m): op for p, m, op in _operations(_schema("local-or-bearer"))}
    assert ops[("/api/v1/entities", "get")]["security"] == [{BEARER_SCHEME: []}, {}]


def test_local_only_schema_is_unchanged():
    schema = _schema("local-only")
    assert BEARER_SCHEME not in schema.get("components", {}).get("securitySchemes", {})
    assert all("security" not in op for _, _, op in _operations(schema))
