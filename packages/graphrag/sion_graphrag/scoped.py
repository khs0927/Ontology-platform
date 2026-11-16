"""Scope-restricted projection for regulation review retrieval (framework plan section 11).

``build_custom_kg`` reads every entity. Before LightRAG sees anything, this removes what the caller
may not use: another project's private entities, relations that touch them, and chunks that
describe them. Rejected relations are always dropped, and the candidate layer stays apart from
the reviewed layer. The filter runs on the projection itself, because dropping a row from an answer
afterwards would not keep it out of retrieval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sion_api import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from .projection import build_custom_kg

REVIEWED_STATES = ("verified",)
CANDIDATE_STATES = ("verified", "unverified")


@dataclass(frozen=True, slots=True)
class ProjectionScope:
    """``project_id`` None means shared public material only."""

    project_id: str | None = None
    include_candidates: bool = False
    at: datetime | None = None
    projection_version: str = "regulation-scoped/1"


def _owner_key(value: object) -> str:
    """Compare project ids the same way whether they arrive as UUIDs or strings."""

    text = str(value).strip()
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def _private_keys(session: Session, project_id: str | None) -> set[str]:
    """Stable keys of entities that belong only to projects other than ``project_id``.

    An entity belongs to a project when it is that project's ``Project`` entity or carries
    ``properties.project_id``. An entity with neither belongs to every project owning an entity its
    ``PART_OF`` chain reaches (a ``Project`` row or any entity owned through
    ``properties.project_id``), in any review state or validity window, so a document linked to
    project material only by relation stays that project's material. With ``project_id`` None every project-owned entity
    is hidden, so the public-only scope never sees project material.
    """

    rows: list[Any] = list(session.scalars(select(models.Entity)))
    explicit: dict[Any, set[str]] = {}
    reached: dict[Any, set[str]] = {}
    for row in rows:
        own: set[str] = set()
        if row.entity_type_id == "Project":
            own.add(_owner_key(row.id))
        owner = (row.properties or {}).get("project_id")
        if owner is not None:
            own.add(_owner_key(owner))
        explicit[row.id] = own
        # Ownership flows down PART_OF from any owned entity, not only from Project rows.
        reached[row.id] = set(own)
    part_of: list[Any] = list(
        session.scalars(select(models.Relation).where(models.Relation.relation_type_id == "PART_OF"))
    )
    edges = [(rel.source_entity_id, rel.target_entity_id) for rel in part_of]
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            inherited = reached.get(target, set()) - reached.setdefault(source, set())
            if inherited:
                reached[source] |= inherited
                changed = True
    scope = None if project_id is None else _owner_key(project_id)
    hidden: set[str] = set()
    for row in rows:
        owners = explicit[row.id] or reached[row.id]
        if owners and scope not in owners:
            hidden.add(row.stable_key)
    return hidden


def build_scoped_kg(session: Session, scope: ProjectionScope) -> dict[str, Any]:
    states = CANDIDATE_STATES if scope.include_candidates else REVIEWED_STATES
    kg = build_custom_kg(session, at=scope.at, review_states=states)
    hidden = _private_keys(session, scope.project_id)
    entities = [e for e in kg["entities"] if e["entity_name"] not in hidden]
    relationships = [r for r in kg["relationships"] if r["src_id"] not in hidden and r["tgt_id"] not in hidden]
    kept = {e["source_id"] for e in entities} | {r["source_id"] for r in relationships}
    return {
        "chunks": [c for c in kg["chunks"] if c["source_id"] in kept],
        "entities": entities,
        "relationships": relationships,
        "projection": {
            "version": scope.projection_version,
            "project_id": scope.project_id,
            "review_states": list(states),
            "hidden_entities": len(hidden),
        },
    }
