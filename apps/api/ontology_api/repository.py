from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models, schemas


def get_entity_type(db: Session, type_id: str) -> models.EntityType | None:
    return db.get(models.EntityType, type_id)


def get_relation_type(db: Session, type_id: str) -> models.RelationType | None:
    return db.get(models.RelationType, type_id)


def create_entity(db: Session, data: schemas.EntityCreate) -> models.Entity:
    row = models.Entity(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_entities(db: Session, *, limit: int = 100, offset: int = 0) -> list[models.Entity]:
    return list(db.scalars(select(models.Entity).order_by(models.Entity.name).offset(offset).limit(limit)))


def get_entity(db: Session, entity_id: str) -> models.Entity | None:
    return db.get(models.Entity, entity_id)


def update_entity(db: Session, row: models.Entity, data: schemas.EntityUpdate) -> models.Entity:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_entity(db: Session, row: models.Entity) -> None:
    db.delete(row)
    db.commit()


def search_entities(db: Session, text_value: str, *, limit: int = 50) -> list[models.Entity]:
    pattern = f"%{text_value}%"
    stmt = select(models.Entity).where(
        or_(models.Entity.name.ilike(pattern), models.Entity.description.ilike(pattern))
    ).order_by(models.Entity.name).limit(limit)
    return list(db.scalars(stmt))


def create_relation(db: Session, data: schemas.RelationCreate) -> models.Relation:
    row = models.Relation(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_relations(db: Session, *, limit: int = 100, offset: int = 0) -> list[models.Relation]:
    return list(db.scalars(select(models.Relation).order_by(models.Relation.created_at).offset(offset).limit(limit)))


def get_relation(db: Session, relation_id: str) -> models.Relation | None:
    return db.get(models.Relation, relation_id)


def delete_relation(db: Session, row: models.Relation) -> None:
    db.delete(row)
    db.commit()


def create_artifact(db: Session, data: schemas.ArtifactCreate) -> models.Artifact:
    row = models.Artifact(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_artifacts(db: Session, *, limit: int = 100, offset: int = 0) -> list[models.Artifact]:
    return list(db.scalars(select(models.Artifact).order_by(models.Artifact.created_at).offset(offset).limit(limit)))


def get_artifact(db: Session, artifact_id: str) -> models.Artifact | None:
    return db.get(models.Artifact, artifact_id)


def create_evidence(db: Session, data: schemas.EvidenceCreate) -> models.Evidence:
    row = models.Evidence(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_evidence(db: Session, *, limit: int = 100, offset: int = 0) -> list[models.Evidence]:
    return list(db.scalars(select(models.Evidence).order_by(models.Evidence.created_at).offset(offset).limit(limit)))


def get_evidence(db: Session, evidence_id: str) -> models.Evidence | None:
    return db.get(models.Evidence, evidence_id)


def delete_evidence(db: Session, row: models.Evidence) -> None:
    db.delete(row)
    db.commit()
