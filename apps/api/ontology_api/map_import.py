from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_map_bridge import MapExport, build_import_plan

from . import models


class MapImportConflict(RuntimeError):
    pass


class MapImportInvalid(RuntimeError):
    pass


class MapImportResult(BaseModel):
    namespace: str
    entities_created: int
    relations_created: int
    evidence_created: int


def import_map(db: Session, export: MapExport) -> MapImportResult:
    plan = build_import_plan(export)

    entity_type_ids = {item.entity_type_id for item in plan.entities}
    known_entity_types = set(
        db.scalars(select(models.EntityType.id).where(models.EntityType.id.in_(entity_type_ids)))
    )
    missing_entity_types = sorted(entity_type_ids - known_entity_types)
    if missing_entity_types:
        raise MapImportInvalid(f"unknown entity types: {', '.join(missing_entity_types)}")

    relation_type_ids = {item.relation_type_id for item in plan.relations}
    known_relation_types = set(
        db.scalars(select(models.RelationType.id).where(models.RelationType.id.in_(relation_type_ids)))
    )
    missing_relation_types = sorted(relation_type_ids - known_relation_types)
    if missing_relation_types:
        raise MapImportInvalid(f"unknown relation types: {', '.join(missing_relation_types)}")

    entity_keys = [item.stable_key for item in plan.entities]
    relation_keys = [item.stable_key for item in plan.relations]

    existing_entities = list(
        db.scalars(select(models.Entity.stable_key).where(models.Entity.stable_key.in_(entity_keys)))
    ) if entity_keys else []
    existing_relations = list(
        db.scalars(select(models.Relation.stable_key).where(models.Relation.stable_key.in_(relation_keys)))
    ) if relation_keys else []

    if existing_entities or existing_relations:
        samples = sorted([*existing_entities, *existing_relations])[:10]
        raise MapImportConflict("map stable keys already exist: " + ", ".join(samples))

    entity_ids: dict[str, str] = {}
    relation_ids: dict[str, str] = {}

    try:
        for item in plan.entities:
            row = models.Entity(
                stable_key=item.stable_key,
                entity_type_id=item.entity_type_id,
                name=item.name,
                category=item.category,
                properties=item.properties,
                ontology_version=export.schema_version,
            )
            db.add(row)
            db.flush()
            entity_ids[item.stable_key] = row.id

        for item in plan.relations:
            row = models.Relation(
                stable_key=item.stable_key,
                source_entity_id=entity_ids[item.source_stable_key],
                target_entity_id=entity_ids[item.target_stable_key],
                relation_type_id=item.relation_type_id,
                verification_state=item.verification_state,
                source_kind=item.source_kind,
                ontology_version=export.schema_version,
                properties=item.properties,
            )
            db.add(row)
            db.flush()
            relation_ids[item.stable_key] = row.id

        for item in plan.evidence:
            db.add(
                models.Evidence(
                    relation_id=relation_ids[item.relation_stable_key],
                    source_uri=item.source_uri,
                    source_locator=item.source_locator,
                    verification_state=item.verification_state,
                    extractor="ontology-map-import/v1",
                    properties=item.properties,
                )
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return MapImportResult(
        namespace=plan.namespace,
        entities_created=len(plan.entities),
        relations_created=len(plan.relations),
        evidence_created=len(plan.evidence),
    )
