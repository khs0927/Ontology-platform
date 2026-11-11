"""Scope-restricted projection for regulation review retrieval (framework plan section 11).

``build_custom_kg`` reads every entity. Before LightRAG sees anything, this removes what the caller
may not use: another project's private entities, relations that touch them, and chunks that
describe them. Rejected relations are always dropped, and the candidate layer stays apart from
the reviewed layer. The filter runs on the projection itself, because dropping a row from an answer
afterwards would not keep it out of retrieval.
"""

from __future__ import annotations

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


def _private_keys(session: Session, project_id: str | None) -> set[str]:
    """Stable keys of entities that belong to a project other than ``project_id``."""

    hidden: set[str] = set()
    for row in session.scalars(select(models.Entity)):
        owner = (row.properties or {}).get("project_id")
        if owner is not None and str(owner) != project_id:
            hidden.add(row.stable_key)
    return hidden


def build_scoped_kg(session: Session, scope: ProjectionScope) -> dict[str, Any]:
    states = CANDIDATE_STATES if scope.include_candidates else REVIEWED_STATES
    kg = build_custom_kg(session, at=scope.at, review_states=states)
    hidden = _private_keys(session, scope.project_id)
    entities = [e for e in kg["entities"] if e["entity_name"] not in hidden]
    relationships = [
        r for r in kg["relationships"] if r["src_id"] not in hidden and r["tgt_id"] not in hidden
    ]
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
