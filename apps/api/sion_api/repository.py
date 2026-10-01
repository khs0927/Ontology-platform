from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .schemas import EntityCreate, EvidenceCreate, RelationCreate, RelationInvalidate


class ConflictError(Exception):
    pass


class MissingReferenceError(Exception):
    pass


def _relation_valid_at(at: datetime):
    return and_(
        or_(models.Relation.valid_from.is_(None), models.Relation.valid_from <= at),
        or_(models.Relation.valid_to.is_(None), models.Relation.valid_to > at),
    )


def seed_core_types(session: Session) -> None:
    entity_types = [
        ("Entity", "Entity"),
        ("Project", "Project"),
        ("Tool", "Tool"),
        ("Concept", "Concept"),
        ("Document", "Document"),
        ("Artifact", "Artifact"),
        ("Dataset", "Dataset"),
        ("SystemComponent", "System Component"),
        ("Workflow", "Workflow"),
        ("Decision", "Decision"),
        ("Deliverable", "Deliverable"),
    ]
    relation_types = [
        ("RELATED_TO", "Related to"),
        ("PART_OF", "Part of"),
        ("USES", "Uses"),
        ("PRODUCES", "Produces"),
        ("DERIVED_FROM", "Derived from"),
        ("REFERENCES", "References"),
        ("IMPLEMENTS", "Implements"),
        ("DEPENDS_ON", "Depends on"),
        ("CONNECTS_TO", "Connects to"),
        ("SUPPORTS", "Supports"),
        ("EXTRACTED_FROM", "Extracted from"),
        ("EVIDENCED_BY", "Evidenced by"),
        ("SUPERSEDES", "Supersedes"),
        ("VERSION_OF", "Version of"),
    ]
    for type_id, label in entity_types:
        if session.get(models.EntityType, type_id) is None:
            session.add(models.EntityType(id=type_id, label=label))
    for type_id, label in relation_types:
        if session.get(models.RelationType, type_id) is None:
            session.add(models.RelationType(id=type_id, label=label))
    session.commit()


def create_entity(session: Session, payload: EntityCreate) -> models.Entity:
    if session.get(models.EntityType, payload.entity_type_id) is None:
        raise MissingReferenceError(f"unknown entity type: {payload.entity_type_id}")
    row = models.Entity(**payload.model_dump())
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"entity stable_key already exists: {payload.stable_key}") from exc
    session.refresh(row)
    return row


def create_relation(session: Session, payload: RelationCreate) -> models.Relation:
    if session.get(models.Entity, payload.source_entity_id) is None:
        raise MissingReferenceError("source entity does not exist")
    if session.get(models.Entity, payload.target_entity_id) is None:
        raise MissingReferenceError("target entity does not exist")
    if session.get(models.RelationType, payload.relation_type_id) is None:
        raise MissingReferenceError(f"unknown relation type: {payload.relation_type_id}")
    row = models.Relation(**payload.model_dump())
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"relation stable_key already exists: {payload.stable_key}"
        ) from exc
    session.refresh(row)
    return row


def create_evidence(session: Session, payload: EvidenceCreate) -> models.Evidence:
    if payload.entity_id and session.get(models.Entity, payload.entity_id) is None:
        raise MissingReferenceError("evidence entity does not exist")
    if payload.relation_id and session.get(models.Relation, payload.relation_id) is None:
        raise MissingReferenceError("evidence relation does not exist")
    row = models.Evidence(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_entities(session: Session, *, limit: int, offset: int) -> list[models.Entity]:
    return list(
        session.scalars(
            select(models.Entity)
            .order_by(models.Entity.created_at, models.Entity.id)
            .offset(offset)
            .limit(limit)
        )
    )


def list_relations(
    session: Session,
    *,
    limit: int,
    offset: int,
    at: datetime | None = None,
    active_only: bool = False,
) -> list[models.Relation]:
    effective_at = at or (datetime.now(timezone.utc) if active_only else None)
    statement = select(models.Relation)
    if effective_at is not None:
        statement = statement.where(_relation_valid_at(effective_at))
    return list(
        session.scalars(
            statement
            .order_by(models.Relation.created_at, models.Relation.id)
            .offset(offset)
            .limit(limit)
        )
    )


def invalidate_relation(
    session: Session,
    relation_id: uuid.UUID,
    payload: RelationInvalidate,
) -> models.Relation:
    row = session.get(models.Relation, relation_id)
    if row is None:
        raise MissingReferenceError("relation does not exist")
    if row.valid_to is not None:
        raise ConflictError("relation is already invalidated")
    if row.valid_from is not None and payload.valid_to < row.valid_from:
        raise ConflictError("valid_to must not precede valid_from")

    row.valid_to = payload.valid_to
    properties = dict(row.properties or {})
    temporal = dict(properties.get("temporal") or {})
    temporal["invalidated_at"] = payload.valid_to.isoformat()
    if payload.reason:
        temporal["reason"] = payload.reason
    properties["temporal"] = temporal
    row.properties = properties
    session.commit()
    session.refresh(row)
    return row


def list_evidence(
    session: Session, *, limit: int, offset: int
) -> list[models.Evidence]:
    return list(
        session.scalars(
            select(models.Evidence)
            .order_by(models.Evidence.created_at, models.Evidence.id)
            .offset(offset)
            .limit(limit)
        )
    )


def get_graph(
    session: Session,
    *,
    limit: int,
    at: datetime | None = None,
    active_only: bool = False,
):
    nodes = list(
        session.scalars(
            select(models.Entity).order_by(models.Entity.created_at).limit(limit)
        )
    )
    node_ids = {node.id for node in nodes}
    if not node_ids:
        return [], []

    effective_at = at or (datetime.now(timezone.utc) if active_only else None)
    statement = select(models.Relation).where(
        models.Relation.source_entity_id.in_(node_ids),
        models.Relation.target_entity_id.in_(node_ids),
    )
    if effective_at is not None:
        statement = statement.where(_relation_valid_at(effective_at))
    edges = list(session.scalars(statement.order_by(models.Relation.created_at)))
    return nodes, edges


def create_artifact(session: Session, payload) -> models.Artifact:
    row = models.Artifact(**payload.model_dump())
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"artifact stable_key already exists: {payload.stable_key}"
        ) from exc
    session.refresh(row)
    return row


def list_artifacts(session: Session, *, limit: int, offset: int) -> list[models.Artifact]:
    return list(
        session.scalars(
            select(models.Artifact)
            .order_by(models.Artifact.created_at, models.Artifact.id)
            .offset(offset)
            .limit(limit)
        )
    )
