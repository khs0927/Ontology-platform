from __future__ import annotations

from pydantic import BaseModel, Field

from .contract import MapExport


class PlannedEntity(BaseModel):
    stable_key: str
    entity_type_id: str
    name: str
    category: str
    properties: dict = Field(default_factory=dict)


class PlannedRelation(BaseModel):
    stable_key: str
    source_stable_key: str
    target_stable_key: str
    relation_type_id: str
    source_kind: str = "imported"
    verification_state: str = "unverified"
    properties: dict = Field(default_factory=dict)


class PlannedEvidence(BaseModel):
    relation_stable_key: str
    source_uri: str
    source_locator: str | None = None
    verification_state: str = "unverified"
    properties: dict = Field(default_factory=dict)


class ImportPlan(BaseModel):
    schema_version: str = "ontology-map-import-plan/v1"
    namespace: str
    source: str
    source_uri: str
    entities: list[PlannedEntity]
    relations: list[PlannedRelation]
    evidence: list[PlannedEvidence]


def _node_key(namespace: str, source_id: str) -> str:
    return f"map:{namespace}:node:{source_id}"


def _relation_key(namespace: str, source_id: str) -> str:
    return f"map:{namespace}:relation:{source_id}"


def build_import_plan(export: MapExport) -> ImportPlan:
    node_keys = {node.id: _node_key(export.namespace, node.id) for node in export.nodes}

    entities = [
        PlannedEntity(
            stable_key=node_keys[node.id],
            entity_type_id=node.entity_type_id,
            name=node.label,
            category=node.category_id,
            properties={
                **node.properties,
                "map_namespace": export.namespace,
                "map_source_id": node.id,
                "map_source": export.source,
                "map_source_uri": export.source_uri,
            },
        )
        for node in export.nodes
    ]

    relations: list[PlannedRelation] = []
    evidence: list[PlannedEvidence] = []
    for relation in export.relations:
        relation_key = _relation_key(export.namespace, relation.id)
        relations.append(
            PlannedRelation(
                stable_key=relation_key,
                source_stable_key=node_keys[relation.source_id],
                target_stable_key=node_keys[relation.target_id],
                relation_type_id=relation.relation_type_id,
                properties={
                    **relation.properties,
                    "map_namespace": export.namespace,
                    "map_source_id": relation.id,
                    "map_source": export.source,
                    "map_source_uri": export.source_uri,
                },
            )
        )
        evidence.append(
            PlannedEvidence(
                relation_stable_key=relation_key,
                source_uri=relation.source_uri or export.source_uri,
                source_locator=relation.source_locator,
                properties={
                    "map_namespace": export.namespace,
                    "map_source_relation_id": relation.id,
                },
            )
        )

    return ImportPlan(
        namespace=export.namespace,
        source=export.source,
        source_uri=export.source_uri,
        entities=entities,
        relations=relations,
        evidence=evidence,
    )
