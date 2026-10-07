from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sion_api import models
from sqlalchemy import select
from sqlalchemy.orm import Session


class GraphImportError(ValueError):
    pass


class MapNode(BaseModel):
    stable_key: str = Field(min_length=1, max_length=500)
    entity_type_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=500)
    category: str | None = None
    description: str | None = None
    external_uri: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ontology_version: str | None = None


class MapEdge(BaseModel):
    stable_key: str = Field(min_length=1, max_length=700)
    source_stable_key: str = Field(min_length=1, max_length=500)
    target_stable_key: str = Field(min_length=1, max_length=500)
    relation_type_id: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: Literal[
        "unverified", "machine_verified", "human_verified", "rejected"
    ] = "unverified"
    source_kind: Literal[
        "user", "document", "file", "database", "api", "mcp", "inferred", "imported"
    ] | None = "imported"
    ontology_version: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class MapExport(BaseModel):
    schema_id: Literal["sion-map-export/v1"] = Field(alias="schema")
    source: str = Field(min_length=1)
    expected_node_count: int | None = Field(default=None, ge=0)
    expected_edge_count: int | None = Field(default=None, ge=0)
    nodes: list[MapNode]
    edges: list[MapEdge]

    @model_validator(mode="after")
    def validate_graph(self):
        node_keys = [node.stable_key for node in self.nodes]
        edge_keys = [edge.stable_key for edge in self.edges]

        if len(node_keys) != len(set(node_keys)):
            raise ValueError("duplicate node stable_key in export")
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("duplicate edge stable_key in export")

        known_nodes = set(node_keys)
        dangling = [
            edge.stable_key
            for edge in self.edges
            if edge.source_stable_key not in known_nodes
            or edge.target_stable_key not in known_nodes
        ]
        if dangling:
            raise ValueError(f"dangling edge references: {', '.join(dangling[:5])}")

        if self.expected_node_count is not None and len(self.nodes) != self.expected_node_count:
            raise ValueError(
                f"node count mismatch: expected {self.expected_node_count}, got {len(self.nodes)}"
            )
        if self.expected_edge_count is not None and len(self.edges) != self.expected_edge_count:
            raise ValueError(
                f"edge count mismatch: expected {self.expected_edge_count}, got {len(self.edges)}"
            )
        return self


class ImportResult(BaseModel):
    created_nodes: int
    skipped_nodes: int
    created_edges: int
    skipped_edges: int


def load_map_export(path: str | Path) -> MapExport:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return MapExport.model_validate(raw)


def import_map_export(session: Session, export: MapExport) -> ImportResult:
    """Non-destructive idempotent import.

    Existing stable keys are skipped, never overwritten or deleted.
    Edges are resolved only from nodes present in the export or already in DB.
    """
    created_nodes = skipped_nodes = created_edges = skipped_edges = 0

    node_by_key: dict[str, models.Entity] = {
        row.stable_key: row
        for row in session.scalars(
            select(models.Entity).where(
                models.Entity.stable_key.in_([n.stable_key for n in export.nodes])
            )
        )
    }

    for node in export.nodes:
        if session.get(models.EntityType, node.entity_type_id) is None:
            raise GraphImportError(f"unknown entity type: {node.entity_type_id}")
        if node.stable_key in node_by_key:
            skipped_nodes += 1
            continue
        row = models.Entity(**node.model_dump())
        session.add(row)
        session.flush()
        node_by_key[node.stable_key] = row
        created_nodes += 1

    for edge in export.edges:
        if session.get(models.RelationType, edge.relation_type_id) is None:
            raise GraphImportError(f"unknown relation type: {edge.relation_type_id}")

        existing = session.scalar(
            select(models.Relation).where(models.Relation.stable_key == edge.stable_key)
        )
        if existing is not None:
            skipped_edges += 1
            continue

        source = node_by_key.get(edge.source_stable_key)
        target = node_by_key.get(edge.target_stable_key)
        if source is None or target is None:
            raise GraphImportError(f"unresolved edge: {edge.stable_key}")

        payload = edge.model_dump(
            exclude={"source_stable_key", "target_stable_key"}
        )
        row = models.Relation(
            **payload,
            source_entity_id=source.id,
            target_entity_id=target.id,
        )
        session.add(row)
        created_edges += 1

    session.commit()
    return ImportResult(
        created_nodes=created_nodes,
        skipped_nodes=skipped_nodes,
        created_edges=created_edges,
        skipped_edges=skipped_edges,
    )
