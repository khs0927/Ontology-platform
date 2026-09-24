from __future__ import annotations

import pytest

from sion_api.config import Settings
from sion_api.main import create_app
from sion_api.security import validate_startup_settings


def production_settings(**overrides):
    values = {
        "database_url": "postgresql+psycopg://user:pass@db.example/app",
        "auto_create_schema": False,
        "ontology_path": "ontology.yaml",
        "map_inventory_path": "inventory.json",
        "cors_origins": (),
        "api_host": "127.0.0.1",
        "local_api_token": "production-token",
        "environment": "production",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_requires_local_bearer_token():
    with pytest.raises(RuntimeError, match="LOCAL_API_TOKEN"):
        validate_startup_settings(production_settings(local_api_token=None))


def test_production_requires_psycopg_postgresql_url():
    with pytest.raises(RuntimeError, match="postgresql\\+psycopg"):
        validate_startup_settings(production_settings(database_url="sqlite:///runtime.db"))


def test_production_disables_schema_auto_creation():
    with pytest.raises(RuntimeError, match="AUTO_CREATE_SCHEMA"):
        validate_startup_settings(production_settings(auto_create_schema=True))


def test_production_rejects_wildcard_host_without_token():
    with pytest.raises(RuntimeError, match="LOCAL_API_TOKEN"):
        validate_startup_settings(
            production_settings(api_host="0.0.0.0", local_api_token=None)
        )


def test_production_requires_exact_migration_head_at_startup(monkeypatch):
    from sion_api import main

    monkeypatch.setenv("SION_ENV", "production")
    monkeypatch.setenv("SION_DATABASE_URL", "postgresql+psycopg://user:pass@db.example/app")
    monkeypatch.setenv("SION_AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("SION_LOCAL_API_TOKEN", "production-token")
    monkeypatch.setattr(main, "check_readiness", lambda engine: {"status": "not_ready"})
    with pytest.raises(RuntimeError, match="readiness"):
        with __import__("fastapi").testclient.TestClient(
            create_app(database_url="postgresql+psycopg://user:pass@db.example/app", auto_create_schema=False)
        ):
            pass
