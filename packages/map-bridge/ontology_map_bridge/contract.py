from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class MapCategory(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class MapNode(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    entity_type_id: str = Field(min_length=1)
    category_id: str = Field(min_length=1)
    properties: dict = Field(default_factory=dict)


class MapRelation(BaseModel):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation_type_id: str = Field(min_length=1)
    source_uri: str | None = None
    source_locator: str | None = None
    properties: dict = Field(default_factory=dict)


class MapExport(BaseModel):
    schema_version: str = "ontology-map-export/v1"
    namespace: str = Field(default="ontology-map", min_length=1)
    source: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    expected_node_count: int = Field(ge=0)
    expected_relation_count: int = Field(ge=0)
    categories: list[MapCategory]
    nodes: list[MapNode]
    relations: list[MapRelation]

    @model_validator(mode="after")
    def validate_graph(self):
        category_ids = [item.id for item in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("duplicate category id")

        node_ids = [item.id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate node id")

        relation_ids = [item.id for item in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("duplicate relation id")

        known_nodes = set(node_ids)
        known_categories = set(category_ids)
        for node in self.nodes:
            if node.category_id not in known_categories:
                raise ValueError(f"unknown category_id: {node.category_id}")

        for relation in self.relations:
            if relation.source_id not in known_nodes:
                raise ValueError(f"unknown relation source_id: {relation.source_id}")
            if relation.target_id not in known_nodes:
                raise ValueError(f"unknown relation target_id: {relation.target_id}")

        if self.expected_node_count != len(self.nodes):
            raise ValueError(
                f"node count mismatch: expected {self.expected_node_count}, got {len(self.nodes)}"
            )
        if self.expected_relation_count != len(self.relations):
            raise ValueError(
                f"relation count mismatch: expected {self.expected_relation_count}, got {len(self.relations)}"
            )
        return self


def load_map_export(path: str | Path) -> MapExport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return MapExport.model_validate(payload)
