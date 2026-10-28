"""Project canonical Sion entities/relations/evidence into a LightRAG custom KG.

PostgreSQL rows stay the source of truth. Every LightRAG entity, relationship
and chunk carries the canonical stable_key so retrieval answers can be traced
back to the row (and its evidence) that produced them.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

# Review buckets (Issue #80 step 1). ``verified`` covers both human and machine
# verification; ``unverified`` is pending review; ``rejected`` was turned down.
REVIEW_STATE_GROUPS: dict[str, frozenset[str]] = {
    "verified": frozenset({"human_verified", "machine_verified"}),
    "unverified": frozenset({"unverified"}),
    "rejected": frozenset({"rejected"}),
}


def resolve_verification_states(review_states: Iterable[str] | None) -> frozenset[str] | None:
    """Map review buckets (verified/unverified/rejected) or raw states to raw states.

    ``None`` means no filtering. Unknown names raise ``ValueError``.
    """
    if review_states is None:
        return None
    raw_states = set().union(*REVIEW_STATE_GROUPS.values())
    resolved: set[str] = set()
    for name in review_states:
        if name in REVIEW_STATE_GROUPS:
            resolved |= REVIEW_STATE_GROUPS[name]
        elif name in raw_states:
            resolved.add(name)
        else:
            raise ValueError(f"unknown review state: {name!r}")
    return frozenset(resolved)

from sion_api import models
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session


def _active_at(at: datetime):
    return and_(
        or_(models.Relation.valid_from.is_(None), models.Relation.valid_from <= at),
        or_(models.Relation.valid_to.is_(None), models.Relation.valid_to > at),
    )


def _relation_query(at: datetime, allowed_states: frozenset[str] | None):
    query = select(models.Relation).where(_active_at(at))
    if allowed_states is not None:
        query = query.where(models.Relation.verification_state.in_(sorted(allowed_states)))
    return query


def _properties_text(properties: dict[str, Any] | None) -> str:
    if not properties:
        return ""
    return json.dumps(properties, ensure_ascii=False, sort_keys=True, default=str)


def _evidence_lines(rows: list[models.Evidence]) -> list[str]:
    return [
        f"evidence: {row.source_uri}"
        + (f" @ {row.source_locator}" if row.source_locator else "")
        + f" ({row.verification_state})"
        for row in rows
    ]


def build_custom_kg(
    session: Session,
    *,
    at: datetime | None = None,
    review_states: Iterable[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return a LightRAG ``custom_kg`` built from relations valid at ``at`` (default: now).

    ``review_states`` restricts relationships (and their weights) to the given
    review buckets (``verified``/``unverified``/``rejected``) or raw
    ``verification_state`` values. ``None`` keeps every relation.
    """
    allowed_states = resolve_verification_states(review_states)
    effective_at = at or datetime.now(timezone.utc)
    if effective_at.tzinfo is None:
        effective_at = effective_at.replace(tzinfo=timezone.utc)

    entities = list(session.scalars(select(models.Entity).order_by(models.Entity.stable_key)))
    relations = list(
        session.scalars(
            _relation_query(effective_at, allowed_states).order_by(models.Relation.stable_key)
        )
    )
    evidence_by_entity: dict[Any, list[models.Evidence]] = defaultdict(list)
    evidence_by_relation: dict[Any, list[models.Evidence]] = defaultdict(list)
    for row in session.scalars(select(models.Evidence).order_by(models.Evidence.source_uri)):
        if row.entity_id is not None:
            evidence_by_entity[row.entity_id].append(row)
        if row.relation_id is not None:
            evidence_by_relation[row.relation_id].append(row)

    by_id = {entity.id: entity for entity in entities}
    chunks: list[dict[str, Any]] = []
    kg_entities: list[dict[str, Any]] = []
    kg_relationships: list[dict[str, Any]] = []

    for entity in entities:
        alias = f"sion:entity:{entity.stable_key}"
        lines = [
            f"{entity.name} ({entity.entity_type_id})",
            f"stable_key: {entity.stable_key}",
        ]
        if entity.description:
            lines.append(entity.description)
        if entity.external_uri:
            lines.append(f"external_uri: {entity.external_uri}")
        if entity.properties:
            lines.append(f"properties: {_properties_text(entity.properties)}")
        lines.extend(_evidence_lines(evidence_by_entity.get(entity.id, [])))
        content = "\n".join(lines)
        chunks.append({"content": content, "source_id": alias, "file_path": f"sion://entity/{entity.stable_key}"})
        kg_entities.append({
            "entity_name": entity.stable_key,
            "entity_type": entity.entity_type_id,
            "description": content,
            "source_id": alias,
            "file_path": f"sion://entity/{entity.stable_key}",
        })

    for relation in relations:
        source = by_id.get(relation.source_entity_id)
        target = by_id.get(relation.target_entity_id)
        if source is None or target is None or source.stable_key == target.stable_key:
            continue
        alias = f"sion:relation:{relation.stable_key}"
        lines = [
            f"{source.name} --{relation.relation_type_id}--> {target.name}",
            f"stable_key: {relation.stable_key}",
            f"verification_state: {relation.verification_state}",
        ]
        if relation.confidence is not None:
            lines.append(f"confidence: {relation.confidence}")
        if relation.properties:
            lines.append(f"properties: {_properties_text(relation.properties)}")
        lines.extend(_evidence_lines(evidence_by_relation.get(relation.id, [])))
        content = "\n".join(lines)
        chunks.append({"content": content, "source_id": alias, "file_path": f"sion://relation/{relation.stable_key}"})
        kg_relationships.append({
            "src_id": source.stable_key,
            "tgt_id": target.stable_key,
            "description": content,
            "keywords": relation.relation_type_id,
            # LightRAG floors a weight at its evidence count (one chunk here);
            # canonical confidence rides on top as a ranking boost.
            "weight": 1.0 + (float(relation.confidence) if relation.confidence is not None else 0.0),
            "source_id": alias,
            "file_path": f"sion://relation/{relation.stable_key}",
        })

    return {"chunks": chunks, "entities": kg_entities, "relationships": kg_relationships}
