from __future__ import annotations

import warnings

from fastapi.testclient import TestClient

from sion_api import main


def test_testclient_runs_lifespan_without_on_event_deprecation(monkeypatch):
    monkeypatch.setenv("SION_ENV", "development")
    app = main.create_app(database_url="sqlite://", auto_create_schema=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200

    assert not [
        warning
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
        and "on_event" in str(warning.message)
    ]


def test_production_readiness_runs_once_during_lifespan_startup(monkeypatch):
    calls: list[object] = []

    def check_readiness(engine):
        calls.append(engine)
        return {"status": "ready"}

    monkeypatch.setenv("SION_ENV", "production")
    monkeypatch.setenv("SION_DATABASE_URL", "postgresql+psycopg://user:pass@db.example/app")
    monkeypatch.setenv("SION_AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("SION_LOCAL_API_TOKEN", "production-token")
    monkeypatch.setattr(main, "check_readiness", check_readiness)

    app = main.create_app(
        database_url="postgresql+psycopg://user:pass@db.example/app",
        auto_create_schema=False,
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200

    assert calls == [app.state.engine]
