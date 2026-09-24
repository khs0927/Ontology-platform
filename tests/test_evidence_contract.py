from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from sion_api.schemas import EvidenceCreate, RelationCreate


def evidence(**changes):
    data = {
        "entity_id": uuid.uuid4(),
        "source_uri": "urn:test:evidence",
    }
    data.update(changes)
    return data


def test_evidence_target_is_strict_xor():
    valid_relation = EvidenceCreate.model_validate(
        evidence(entity_id=None, relation_id=uuid.uuid4(), source_uri="urn:test")
    )
    assert valid_relation.entity_id is None
    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate(evidence(entity_id=uuid.uuid4(), relation_id=uuid.uuid4()))
    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate(evidence(entity_id=None, relation_id=None))


def test_evidence_requires_one_source_and_accepts_artifact_only():
    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate({"entity_id": uuid.uuid4()})
    row = EvidenceCreate.model_validate({"entity_id": uuid.uuid4(), "artifact_id": uuid.uuid4()})
    assert row.source_uri is None
    assert row.relation_id is None


def test_evidence_hash_and_literal_enums_are_validated():
    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate(evidence(excerpt_hash="sha256:bad"))
    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate(evidence(verification_state="unknown"))
    with pytest.raises(ValidationError):
        RelationCreate.model_validate(
            {
                "source_entity_id": uuid.uuid4(),
                "target_entity_id": uuid.uuid4(),
                "relation_type_id": "RELATED_TO",
                "source_kind": "unknown",
            }
        )
    row = EvidenceCreate.model_validate(evidence(excerpt_hash="sha256:" + "a" * 64))
    assert row.excerpt_hash.startswith("sha256:")
