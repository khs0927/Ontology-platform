from __future__ import annotations

import pytest
from sqlalchemy import select

from sion_api.db import Base, build_engine, build_session_factory
from sion_api.models import Entity
from sion_api.repository import seed_core_types
from sion_ingestion.dlp import scan_payload
from sion_ingestion.map_import import MapDLPError, MapExport, import_map_export


SYNTHETIC_HMAC_KEY = b"synthetic-map-dlp-key-not-for-production"


def factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        seed_core_types(session)
    return session_factory


def map_export(*, node_property: str, node_value: str) -> MapExport:
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "synthetic-map-dlp-fixture",
            "nodes": [
                {
                    "stable_key": "project:dlp-fixture",
                    "entity_type_id": "Project",
                    "name": "DLP fixture",
                    "properties": {node_property: node_value},
                }
            ],
            "edges": [],
        }
    )


def test_synthetic_secret_fails_closed_before_canonicalization_and_rolls_back(monkeypatch):
    session_factory = factory()
    secret_fixture = "sion_test_secret-abcdef123456"
    export = map_export(node_property="credential", node_value=secret_fixture)

    def canonicalization_must_not_run(_payload):
        raise AssertionError("canonicalization ran before the DLP gate")

    monkeypatch.setattr("sion_ingestion.map_import.canonical_hash", canonicalization_must_not_run)

    with session_factory() as session:
        pending = Entity(
            stable_key="project:pending-before-dlp-rejection",
            entity_type_id="Project",
            name="Pending",
        )
        session.add(pending)
        session.flush()

        with pytest.raises(MapDLPError) as raised:
            import_map_export(session, export, dlp_hmac_key=SYNTHETIC_HMAC_KEY)

        assert secret_fixture not in str(raised.value)
        assert session.scalars(select(Entity)).all() == []

    with session_factory() as session:
        assert session.scalar(
            select(Entity).where(Entity.stable_key == pending.stable_key)
        ) is None


def test_tokenized_pii_sanitized_payload_is_the_one_imported():
    session_factory = factory()
    pii_fixture = "map.person@example.test"
    export = map_export(node_property="contact", node_value=pii_fixture)

    with session_factory() as session:
        result = import_map_export(session, export, dlp_hmac_key=SYNTHETIC_HMAC_KEY)
        stored = session.scalar(
            select(Entity).where(Entity.stable_key == "project:dlp-fixture")
        )

    assert result.created_nodes == 1
    assert stored is not None
    assert stored.properties["contact"].startswith("[PII:")
    assert pii_fixture not in str(stored.properties)


def test_pre_sanitized_decision_avoids_second_scan_and_keeps_token_in_db(monkeypatch):
    session_factory = factory()
    pii_fixture = "bridge.person@example.test"
    export = map_export(node_property="contact", node_value=pii_fixture)
    decision = scan_payload(
        export.model_dump(by_alias=True), hmac_key=SYNTHETIC_HMAC_KEY
    )
    assert not decision.allowed
    assert decision.action == "tokenized"

    def second_scan_must_not_run(*args, **kwargs):
        raise AssertionError("bridge boundary rescanned pre-sanitized payload")

    monkeypatch.setattr("sion_ingestion.map_import.scan_payload", second_scan_must_not_run)
    with session_factory() as session:
        result = import_map_export(
            session, export, already_scanned=decision, dlp_hmac_key=None
        )
        stored = session.scalar(
            select(Entity).where(Entity.stable_key == "project:dlp-fixture")
        )

    assert result.created_nodes == 1
    assert stored is not None
    assert stored.properties["contact"].startswith("[PII:")
    assert pii_fixture not in str(stored.properties)


def test_public_import_still_scans_without_hmac_key_and_fails_closed():
    session_factory = factory()
    pii_fixture = "public.person@example.test"
    export = map_export(node_property="contact", node_value=pii_fixture)

    with session_factory() as session:
        with pytest.raises(MapDLPError):
            import_map_export(session, export)
        assert session.scalars(select(Entity)).all() == []
