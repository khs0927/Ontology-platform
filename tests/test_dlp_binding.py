"""Decision-binding contracts for DLP-decision trust and edge identity.

A ``DLPDecision`` handed to ``import_map_export`` as a trusted boundary is only
as trustworthy as the binding it carries. These tests are exact oracles against
the production modules: a failure names a real gap in ``dlp.py`` or
``map_import.py``, and is fixed there rather than weakened here.
"""

from __future__ import annotations

import dataclasses
import time

import pytest
from sqlalchemy import select

from sion_api.db import Base, build_engine, build_session_factory
from sion_api.models import Entity, Relation
from sion_api.repository import seed_core_types
from sion_ingestion.dlp import (
    DECISION_TTL_SECONDS,
    DLP_POLICY_VERSION,
    MAX_DECISION_TTL_SECONDS,
    DLPDecision,
    canonical_payload_digest,
    scan_payload,
)
from sion_ingestion.map_import import (
    CANONICAL_EDGE_ENDPOINT_FIELDS,
    GraphIdentityConflictError,
    MapDLPBindingError,
    MapDLPError,
    MapExport,
    canonical_hash,
    edge_canonical_payload,
    import_map_export,
)


SYNTHETIC_HMAC_KEY = b"synthetic-dlp-binding-key-not-for-production"
SECRET = "sion_test_secret-abcdef123456"
PII = "binding.person@example.test"


def factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        seed_core_types(session)
    return session_factory


def _node(key: str, name: str = "Binding node", **extra) -> dict:
    payload = {
        "stable_key": key,
        "entity_type_id": "Project",
        "name": name,
        "properties": {},
    }
    payload.update(extra)
    return payload


def _edge(stable_key: str, source: str, target: str) -> dict:
    return {
        "stable_key": stable_key,
        "source_stable_key": source,
        "target_stable_key": target,
        "relation_type_id": "RELATED_TO",
    }


def _export(nodes: list[dict], edges: list[dict] | None = None) -> MapExport:
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "dlp-binding-fixture",
            "nodes": nodes,
            "edges": edges or [],
        }
    )


def _entities(session) -> list[Entity]:
    return list(session.scalars(select(Entity)))


def _relations(session) -> list[Relation]:
    return list(session.scalars(select(Relation)))


# ---------------------------------------------------------------------------
# 1. the decision itself carries the binding
# ---------------------------------------------------------------------------


def test_scanned_decision_is_bound_to_its_exact_payload():
    payload = {"schema": "sion-map-export/v1", "source": "s", "nodes": [], "edges": []}

    decision = scan_payload(payload)

    assert decision.policy_version == DLP_POLICY_VERSION
    assert decision.source_digest == canonical_payload_digest(payload)
    assert decision.payload_digest == canonical_payload_digest(decision.sanitized_payload)
    assert decision.issued_at > 0
    assert 0 < decision.expires_at - decision.issued_at <= MAX_DECISION_TTL_SECONDS


def test_decision_binding_is_ordered_independent_of_payload_key_order():
    first = scan_payload({"a": 1, "b": 2})
    second = scan_payload({"b": 2, "a": 1})

    assert first.source_digest == second.source_digest


def test_to_dict_exposes_binding_without_exposing_payload_data():
    decision = scan_payload({"note": "clean"})

    exported = decision.to_dict()

    assert exported["policy_version"] == DLP_POLICY_VERSION
    assert exported["payload_digest"] == decision.payload_digest
    assert exported["source_digest"] == decision.source_digest
    assert "sanitized_payload" not in exported
    assert "signature" not in exported


# ---------------------------------------------------------------------------
# 2. policy / HMAC / freshness enforcement on the decision itself
# ---------------------------------------------------------------------------


def test_policy_version_mismatch_is_rejected():
    payload = {"a": 1}
    decision = dataclasses.replace(scan_payload(payload), policy_version="sion-dlp/v1")

    ok, reason = decision.verify_binding(payload=payload)

    assert ok is False
    assert reason == "policy_version_mismatch"


def test_stale_decision_is_rejected_after_its_expiry():
    payload = {"a": 1}
    decision = scan_payload(payload)

    ok, reason = decision.verify_binding(
        payload=payload, now=time.time() + DECISION_TTL_SECONDS + 1
    )

    assert ok is False
    assert reason == "stale_decision"


def test_decision_claiming_an_over_long_lifetime_is_treated_as_stale():
    payload = {"a": 1}
    now = int(time.time())
    decision = dataclasses.replace(
        scan_payload(payload), issued_at=now, expires_at=now + 10 * MAX_DECISION_TTL_SECONDS
    )

    ok, reason = decision.verify_binding(payload=payload, now=float(now))

    assert ok is False
    assert reason == "stale_decision"


def test_tampered_payload_digest_is_rejected():
    decision = scan_payload({"a": 1})

    tampered = dataclasses.replace(decision, payload_digest="0" * 64)
    ok, reason = tampered.verify_binding(payload={"a": 1})

    assert ok is False
    assert reason == "payload_digest_mismatch"


def test_hmac_key_mismatch_is_rejected():
    payload = {"a": 1}
    decision = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)
    assert decision.signature and decision.signer_id

    ok, reason = decision.verify_binding(
        payload=payload, key=b"a-different-synthetic-binding-key"
    )

    assert ok is False
    assert reason == "signer_key_mismatch"


def test_unsigned_decision_is_refused_when_a_key_is_supplied():
    payload = {"a": 1}
    decision = scan_payload(payload)
    assert decision.signature == ""

    ok, reason = decision.verify_binding(payload=payload, key=SYNTHETIC_HMAC_KEY)

    assert ok is False
    assert reason == "signer_binding_missing"


def test_tampered_envelope_breaks_the_signature():
    payload = {"a": 1}
    decision = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)

    tampered = dataclasses.replace(decision, issued_at=decision.issued_at + 5)
    ok, reason = tampered.verify_binding(payload=payload, key=SYNTHETIC_HMAC_KEY)

    assert ok is False
    assert reason == "signer_signature_mismatch"


def test_signature_reason_does_not_leak_the_key():
    payload = {"a": 1}
    decision = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)

    ok, reason = decision.verify_binding(payload=payload, key=b"wrong-synthetic-key")

    assert ok is False
    assert SYNTHETIC_HMAC_KEY.decode() not in reason


# ---------------------------------------------------------------------------
# 3. map_import refuses unverified trusted decisions, after a rollback
# ---------------------------------------------------------------------------


def test_forged_allowed_decision_carrying_a_secret_is_rolled_back_and_refused():
    session_factory = factory()
    forged_payload = {
        "schema": "sion-map-export/v1",
        "source": "forged-binding",
        "nodes": [_node("project:forged-binding", properties={"credential": SECRET})],
        "edges": [],
    }
    forged = DLPDecision(True, "allowed", forged_payload)
    caller_export = _export([_node("project:caller-binding")])

    with session_factory() as session:
        with pytest.raises(MapDLPBindingError):
            import_map_export(session, caller_export, already_scanned=forged)
        assert _entities(session) == []

    with session_factory() as session:
        assert _entities(session) == []


def test_stale_decision_for_this_export_is_rolled_back_and_refused():
    session_factory = factory()
    export = _export([_node("project:stale-binding")])
    decision = scan_payload(export.model_dump(by_alias=True))
    expired = dataclasses.replace(
        decision,
        issued_at=decision.issued_at - 10 * MAX_DECISION_TTL_SECONDS,
        expires_at=decision.expires_at - 10 * MAX_DECISION_TTL_SECONDS,
    )

    with session_factory() as session:
        with pytest.raises(MapDLPBindingError) as raised:
            import_map_export(session, export, already_scanned=expired)
        assert "stale_decision" in str(raised.value)
        assert _entities(session) == []


def test_decision_for_a_different_export_is_rolled_back_and_refused():
    session_factory = factory()
    other = _export([_node("project:other-binding", name="Other")])
    decision = scan_payload(other.model_dump(by_alias=True))
    caller_export = _export([_node("project:caller-binding", name="Caller")])

    with session_factory() as session:
        with pytest.raises(MapDLPBindingError):
            import_map_export(session, caller_export, already_scanned=decision)
        assert _entities(session) == []

    with session_factory() as session:
        assert _entities(session) == []


def test_decision_whose_digest_was_edited_is_rolled_back_and_refused():
    session_factory = factory()
    export = _export([_node("project:edited-binding")])
    decision = scan_payload(export.model_dump(by_alias=True))
    edited = dataclasses.replace(decision, payload_digest="0" * 64)

    with session_factory() as session:
        with pytest.raises(MapDLPBindingError):
            import_map_export(session, export, already_scanned=edited)
        assert _entities(session) == []


def test_matching_signed_tokenized_decision_is_still_accepted():
    session_factory = factory()
    export = _export([_node("project:signed-binding", properties={"contact": PII})])
    decision = scan_payload(export.model_dump(by_alias=True), hmac_key=SYNTHETIC_HMAC_KEY)
    assert decision.action == "tokenized"

    with session_factory() as session:
        result = import_map_export(session, export, already_scanned=decision)
        stored = session.scalar(
            select(Entity).where(Entity.stable_key == "project:signed-binding")
        )

    assert result.created_nodes == 1
    assert stored is not None
    assert stored.properties["contact"].startswith("[PII:")
    assert PII not in str(stored.properties)


def test_bridge_style_decision_over_its_own_sanitized_export_is_accepted():
    """The CLI adopts the sanitized export, then passes the same decision back."""
    session_factory = factory()
    raw = _export([_node("project:bridge-binding", properties={"contact": PII})])
    decision = scan_payload(raw.model_dump(by_alias=True), hmac_key=SYNTHETIC_HMAC_KEY)
    sanitized_export = MapExport.model_validate(decision.sanitized_payload)

    with session_factory() as session:
        result = import_map_export(
            session, sanitized_export, already_scanned=decision, dlp_hmac_key=SYNTHETIC_HMAC_KEY
        )
        stored = session.scalar(
            select(Entity).where(Entity.stable_key == "project:bridge-binding")
        )

    assert result.created_nodes == 1
    assert stored is not None
    assert stored.properties["contact"].startswith("[PII:")


def test_mismatched_tokenized_decision_still_raises_the_dlp_error():
    session_factory = factory()
    decision = DLPDecision(False, "tokenized", {"not": "a map export"})

    with session_factory() as session:
        with pytest.raises(MapDLPError):
            import_map_export(
                session, _export([_node("project:mismatched-binding")]), already_scanned=decision
            )
        assert _entities(session) == []


def test_binding_error_is_a_map_dlp_error_subclass():
    """Callers that only catch ``MapDLPError`` keep working."""

    assert issubclass(MapDLPBindingError, MapDLPError)


# ---------------------------------------------------------------------------
# 4. edge canonical hash covers its endpoints
# ---------------------------------------------------------------------------


def test_edge_canonical_payload_contains_both_endpoints():
    edge = _export(
        [_node("project:ea"), _node("project:eb")], [_edge("edge:1", "project:ea", "project:eb")]
    ).edges[0]

    payload = edge_canonical_payload(edge)

    for field in CANONICAL_EDGE_ENDPOINT_FIELDS:
        assert field in payload
    assert payload["source_stable_key"] == "project:ea"
    assert payload["target_stable_key"] == "project:eb"


def test_rewiring_an_edge_under_the_same_stable_key_is_a_conflict():
    session_factory = factory()
    nodes = [_node("project:a"), _node("project:b"), _node("project:c")]
    first = _export(nodes, [_edge("edge:1", "project:a", "project:b")])
    rewired = _export(nodes, [_edge("edge:1", "project:a", "project:c")])

    with session_factory() as session:
        import_map_export(session, first)

    with session_factory() as session:
        with pytest.raises(GraphIdentityConflictError):
            import_map_export(session, rewired)
        assert len(_relations(session)) == 1
        # The stored graph still points at the original endpoints.
        stored = _relations(session)[0]
        target = session.get(Entity, stored.target_entity_id)
        assert target.stable_key == "project:b"


def test_unchanged_edge_is_still_skipped_not_conflicted():
    session_factory = factory()
    nodes = [_node("project:a"), _node("project:b")]
    export = _export(nodes, [_edge("edge:1", "project:a", "project:b")])

    with session_factory() as session:
        first = import_map_export(session, export)
        second = import_map_export(session, export)

    assert first.created_edges == 1
    assert second.created_edges == 0
    assert second.skipped_edges == 1


def test_edge_canonical_hash_ignores_only_the_stored_hash_property():
    base = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "s",
            "nodes": [_node("project:a"), _node("project:b")],
            "edges": [_edge("edge:1", "project:a", "project:b")],
        }
    ).edges[0]
    with_hash = base.model_copy(
        update={"properties": {"__sion_canonical_hash": "deadbeef"}}
    )

    assert canonical_hash(edge_canonical_payload(base)) == canonical_hash(
        edge_canonical_payload(with_hash)
    )
