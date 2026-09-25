"""Fail-closed DLP gate coverage for every authenticated API write sink."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sion_api.db import build_session_factory
from sion_api.main import create_app
from sion_api.models import Artifact, Entity, Evidence, Relation


SYNTHETIC_HMAC_KEY = "synthetic-api-dlp-key-not-for-production"
SECRET_FIXTURE = "sion_test_secret-abcdef123456"
PII_FIXTURE = "api.person@example.test"


@pytest.fixture(autouse=True)
def no_hmac_key(monkeypatch):
    """Most gate cases must run with tokenization unavailable, i.e. fail closed."""

    monkeypatch.delenv("SION_DLP_HMAC_KEY", raising=False)


@pytest.fixture
def api(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'dlp-gate.sqlite'}"
    app = create_app(database_url=database_url, auto_create_schema=True)
    with TestClient(app) as client:
        yield client, app


def rows(app, model):
    factory = build_session_factory(app.state.engine)
    with factory() as session:
        return list(session.scalars(select(model)))


def entity_payload(**overrides):
    payload = {
        "stable_key": "project:dlp-gate",
        "entity_type_id": "Project",
        "name": "DLP gate fixture",
        "properties": {},
    }
    payload.update(overrides)
    return payload


def create_entity(client, **overrides):
    return client.post("/api/v1/entities", json=entity_payload(**overrides))


def test_secret_in_entity_name_is_rejected_before_commit(api, caplog):
    client, app = api

    with caplog.at_level(logging.WARNING, logger="sion_api.dlp"):
        response = create_entity(client, name=f"gateway {SECRET_FIXTURE}")

    assert response.status_code == 422
    assert SECRET_FIXTURE not in response.text
    assert SECRET_FIXTURE not in caplog.text
    assert rows(app, Entity) == []
    assert response.json()["detail"]["dlp"]["findings"][0]["classification"] == "SECRET"
    assert "sanitized_payload" not in response.json()["detail"]["dlp"]


def test_secret_in_entity_properties_is_rejected(api):
    client, app = api

    response = create_entity(client, properties={"api_key": SECRET_FIXTURE})

    assert response.status_code == 422
    assert SECRET_FIXTURE not in response.text
    assert rows(app, Entity) == []


def test_pii_fails_closed_without_tokenization_key(api):
    client, app = api

    response = create_entity(client, properties={"contact": PII_FIXTURE})

    assert response.status_code == 422
    assert response.json()["detail"]["dlp"]["metadata"]["reason"] == (
        "pii_tokenization_key_required"
    )
    assert PII_FIXTURE not in response.text
    assert rows(app, Entity) == []


def test_pii_is_tokenized_and_persisted_sanitized_when_key_is_configured(api, monkeypatch):
    client, app = api
    monkeypatch.setenv("SION_DLP_HMAC_KEY", SYNTHETIC_HMAC_KEY)

    response = create_entity(client, properties={"contact": PII_FIXTURE})

    assert response.status_code == 201, response.text
    assert PII_FIXTURE not in response.text
    stored = rows(app, Entity)
    assert len(stored) == 1
    assert stored[0].properties["contact"].startswith("[PII:")


def test_gate_runs_before_the_repository_write(api, monkeypatch):
    client, _app = api

    def create_entity_must_not_run(*args, **kwargs):
        raise AssertionError("repository write ran before the DLP gate")

    monkeypatch.setattr("sion_api.main.repository.create_entity", create_entity_must_not_run)
    response = create_entity(client, properties={"credential": SECRET_FIXTURE})

    assert response.status_code == 422


def test_relation_secret_is_rejected(api):
    client, app = api
    source = create_entity(client, stable_key="project:source", name="Source").json()
    target = create_entity(client, stable_key="project:target", name="Target").json()

    response = client.post(
        "/api/v1/relations",
        json={
            "stable_key": "project:source:RELATED_TO:project:target",
            "source_entity_id": source["id"],
            "target_entity_id": target["id"],
            "relation_type_id": "RELATED_TO",
            "properties": {"note": f"authorization: {SECRET_FIXTURE}"},
        },
    )

    assert response.status_code == 422
    assert SECRET_FIXTURE not in response.text
    assert rows(app, Relation) == []


def test_artifact_storage_uri_secret_is_rejected(api):
    client, app = api

    response = client.post(
        "/api/v1/artifacts",
        json={
            "stable_key": "artifact:dlp-gate",
            "name": "sample.dxf",
            "storage_uri": f"gdrive://token@{SECRET_FIXTURE}/objects/sample.dxf",
            "properties": {},
        },
    )

    assert response.status_code == 422
    assert rows(app, Artifact) == []


def test_evidence_source_uri_contract_reference_is_allowed(api):
    client, app = api
    entity = create_entity(client).json()

    response = client.post(
        "/api/v1/evidence",
        json={
            "entity_id": entity["id"],
            "source_uri": "urn:test:user-confirmed",
            "properties": {},
        },
    )

    assert response.status_code == 201, response.text
    stored = rows(app, Evidence)
    assert len(stored) == 1
    assert stored[0].source_uri == "urn:test:user-confirmed"


def test_source_uri_cannot_smuggle_pii_or_secret(api):
    client, app = api
    entity = create_entity(client).json()

    for smuggled in (
        f"file:///{PII_FIXTURE}",
        f"urn:test:{SECRET_FIXTURE}",
    ):
        response = client.post(
            "/api/v1/evidence",
            json={
                "entity_id": entity["id"],
                "source_uri": smuggled,
                "properties": {},
            },
        )
        assert response.status_code == 422, response.text
        assert smuggled not in response.text

    assert rows(app, Evidence) == []


def test_nested_properties_source_uri_is_not_exempt(api):
    client, app = api
    entity = create_entity(client).json()

    response = client.post(
        "/api/v1/evidence",
        json={
            "entity_id": entity["id"],
            "source_uri": "urn:test:user-confirmed",
            "properties": {"source_uri": PII_FIXTURE},
        },
    )

    assert response.status_code == 422
    assert PII_FIXTURE not in response.text
    assert rows(app, Evidence) == []


def test_embedding_model_secret_is_rejected(api):
    client, app = api
    entity = create_entity(client).json()

    response = client.post(
        "/api/v1/embeddings",
        json={
            "entity_id": entity["id"],
            "model": f"text-embedding-{SECRET_FIXTURE}",
            "embedding": [1.0, 0.0, 0.0],
            "properties": {},
        },
    )

    assert response.status_code == 422
    assert SECRET_FIXTURE not in response.text


def test_vector_search_payload_secret_is_rejected(api):
    client, _app = api

    response = client.post(
        "/api/v1/vector/search",
        json={"model": f"test/{SECRET_FIXTURE}", "embedding": [1.0, 0.0, 0.0], "limit": 5},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["sink"] == "vector_search"
    assert SECRET_FIXTURE not in response.text


def test_clean_payloads_still_reach_the_sink(api):
    client, app = api
    entity = create_entity(client).json()

    assert client.post(
        "/api/v1/vector/search",
        json={"model": "test/free-model", "embedding": [1.0, 0.0, 0.0], "limit": 5},
    ).status_code == 503
    assert len(rows(app, Entity)) == 1
    assert entity["id"]
