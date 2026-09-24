from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_api import models
from sion_ingestion.dlp import DLPDecision, scan_payload


class GraphImportError(ValueError):
    pass


class GraphIdentityConflictError(GraphImportError):
    """An existing graph identity has a different canonical payload."""


class MapDLPError(GraphImportError):
    """A map export was rejected by the fail-closed DLP gate."""


CANONICAL_NODE_FIELDS = (
    "entity_type_id", "name", "category", "description", "external_uri",
    "properties", "ontology_version",
)
CANONICAL_EDGE_FIELDS = (
    "relation_type_id", "confidence", "verification_state", "source_kind",
    "ontology_version", "properties",
)
CANONICAL_HASH_PROPERTY = "__sion_canonical_hash"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def node_canonical_payload(node: MapNode | None = None, **values: Any) -> dict[str, Any]:
    raw = node.model_dump() if node is not None else values
    result = {key: raw.get(key) for key in CANONICAL_NODE_FIELDS}
    if isinstance(result.get("properties"), dict):
        result["properties"] = {k: v for k, v in result["properties"].items() if k != CANONICAL_HASH_PROPERTY}
    return result


def edge_canonical_payload(edge: MapEdge | None = None, **values: Any) -> dict[str, Any]:
    raw = edge.model_dump() if edge is not None else values
    result = {key: raw.get(key) for key in CANONICAL_EDGE_FIELDS}
    if isinstance(result.get("properties"), dict):
        result["properties"] = {k: v for k, v in result["properties"].items() if k != CANONICAL_HASH_PROPERTY}
    return result


def hash_upsert_conflict(existing_hash: str | None, incoming_hash: str) -> bool:
    """Return true only when a present identity hash differs from the new one."""
    return existing_hash is not None and existing_hash != incoming_hash


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


def import_map_export(
    session: Session,
    export: MapExport,
    *,
    dlp_hmac_key: bytes | str | None = None,
    already_scanned: DLPDecision | None = None,
    pre_sanitized: DLPDecision | None = None,
) -> ImportResult:
    """Non-destructive idempotent import with a pre-write DLP gate.

    Public callers get a fail-closed scan of the complete export. The bridge may
    pass the decision from its pre-sink boundary as ``already_scanned``; that is
    an explicit trusted-boundary exception, so a tokenized PII export is not
    scanned a second time without the HMAC key. Only the decision's sanitized
    payload is eligible for canonical hashing and graph writes.

    A same-hash identity is skipped; a different hash raises
    ``GraphIdentityConflictError`` after rolling back the import.
    """
    if already_scanned is not None and pre_sanitized is not None:
        raise TypeError("pass only one trusted DLP decision")
    decision = already_scanned or pre_sanitized
    if decision is None:
        decision = scan_payload(
            export.model_dump(by_alias=True),
            hmac_key=dlp_hmac_key,
        )
    if not decision.allowed:
        if decision.action != "tokenized" or not isinstance(decision.sanitized_payload, dict):
            session.rollback()
            reason = decision.metadata.get("reason", "payload_not_allowed")
            raise MapDLPError(
                f"map export rejected by DLP gate: action={decision.action}, reason={reason}"
            )
        try:
            export = MapExport.model_validate(decision.sanitized_payload)
        except Exception:
            session.rollback()
            raise MapDLPError(
                "map export rejected by DLP gate: sanitized payload is invalid"
            ) from None
    elif isinstance(decision.sanitized_payload, dict):
        export = MapExport.model_validate(decision.sanitized_payload)
    else:
        session.rollback()
        raise MapDLPError("map export rejected by DLP gate: sanitized payload is invalid")

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
            existing = node_by_key[node.stable_key]
            existing_hash = (existing.properties or {}).get(CANONICAL_HASH_PROPERTY)
            if existing_hash is None:
                existing_hash = canonical_hash(node_canonical_payload(**{
                    key: getattr(existing, key) for key in CANONICAL_NODE_FIELDS
                }))
            incoming_hash = canonical_hash(node_canonical_payload(node))
            if hash_upsert_conflict(existing_hash, incoming_hash):
                session.rollback()
                raise GraphIdentityConflictError(
                    f"node identity conflict: {node.stable_key}"
                )
            skipped_nodes += 1
            continue
        payload = node.model_dump()
        payload_hash = canonical_hash(node_canonical_payload(node))
        payload["properties"] = dict(payload["properties"] or {})
        payload["properties"][CANONICAL_HASH_PROPERTY] = payload_hash
        row = models.Entity(**payload)
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
        source = node_by_key.get(edge.source_stable_key)
        target = node_by_key.get(edge.target_stable_key)
        if source is None or target is None:
            raise GraphImportError(f"unresolved edge: {edge.stable_key}")
        if existing is not None:
            existing_hash = (existing.properties or {}).get(CANONICAL_HASH_PROPERTY)
            if existing_hash is None:
                existing_hash = canonical_hash(edge_canonical_payload(**{
                    key: getattr(existing, key) for key in CANONICAL_EDGE_FIELDS
                }))
            incoming_hash = canonical_hash(edge_canonical_payload(edge))
            if hash_upsert_conflict(existing_hash, incoming_hash):
                session.rollback()
                raise GraphIdentityConflictError(
                    f"edge identity conflict: {edge.stable_key}"
                )
            skipped_edges += 1
            continue

        payload = edge.model_dump(
            exclude={"source_stable_key", "target_stable_key"}
        )
        payload_hash = canonical_hash(edge_canonical_payload(edge))
        payload["properties"] = dict(payload["properties"] or {})
        payload["properties"][CANONICAL_HASH_PROPERTY] = payload_hash
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
