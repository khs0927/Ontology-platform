"""Versioned interchange contracts. Coordinates are millimetres in world space."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(allow_inf_nan=False)]
Point = tuple[Number, Number, Number]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceRef(Contract):
    drawing_id: Identifier
    revision: Digest
    format: Literal["DXF", "DWG"]
    layout: str = "Model"
    handle: Annotated[str, Field(pattern=r"^[0-9A-F]+$")]
    insert_path: list[str] = Field(default_factory=list)


class Geometry(Contract):
    kind: Literal["LINE", "LWPOLYLINE", "CIRCLE", "ARC", "UNSUPPORTED"]
    points: list[Point] = Field(default_factory=list)
    radius: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    start_angle: Number | None = None
    end_angle: Number | None = None
    closed: bool = False
    coordinate_system: Literal["WCS"] = "WCS"
    units: Literal["mm"] = "mm"

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind == "LINE" and len(self.points) != 2:
            raise ValueError("LINE requires two endpoints")
        if self.kind == "LWPOLYLINE" and len(self.points) < 2:
            raise ValueError("LWPOLYLINE requires at least two vertices")
        if self.kind in {"ARC", "CIRCLE"}:
            if len(self.points) != 1 or self.radius is None:
                raise ValueError("ARC/CIRCLE require one center and a radius")
        if self.kind == "ARC" and (self.start_angle is None or self.end_angle is None):
            raise ValueError("ARC requires start and end angles in degrees")
        return self


class Entity(Contract):
    id: Identifier
    source: SourceRef
    cad_type: str
    layer: str
    layer_locked: bool = False
    geometry: Geometry
    analysis_supported: bool
    limitations: list[str] = Field(default_factory=list)


class Evidence(Contract):
    method: str
    value: str
    score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    calibrated: Literal[False] = False


class SemanticObject(Contract):
    id: Identifier
    class_uri: str
    status: Literal["candidate"] = "candidate"
    entity_ids: list[Identifier] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Edge(Contract):
    source: Identifier
    target: Identifier
    graph: Literal["topology", "semantic", "edit"]
    relation: Literal["touches_at_endpoint", "represented_by", "requires_update"]
    evidence: str

    @model_validator(mode="after")
    def validate_graph(self):
        expected = {
            "touches_at_endpoint": "topology",
            "represented_by": "semantic",
            "requires_update": "edit",
        }
        if expected[self.relation] != self.graph:
            raise ValueError("Relation and graph do not match")
        return self


class Drawing(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    drawing_id: Identifier
    revision: Digest
    source_name: str
    source_format: Literal["DXF"] = "DXF"
    source_units: Literal["mm", "cm", "m", "in", "ft"]
    unit_evidence: Literal["header", "user_override"]
    scope: Literal["modelspace_top_level"] = "modelspace_top_level"
    topology_tolerance_mm: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 0.1
    entities: list[Entity] = Field(default_factory=list)
    semantic_objects: list[SemanticObject] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        entity_ids = {e.id for e in self.entities}
        semantic_ids = {s.id for s in self.semantic_objects}
        if len(entity_ids) != len(self.entities) or len(semantic_ids) != len(self.semantic_objects):
            raise ValueError("Duplicate object IDs")
        if entity_ids & semantic_ids:
            raise ValueError("Entity and semantic IDs must be disjoint")
        source_keys = set()
        for entity in self.entities:
            ref = entity.source
            if (ref.drawing_id, ref.revision, ref.format) != (
                self.drawing_id,
                self.revision,
                self.source_format,
            ):
                raise ValueError("Source identity does not belong to this drawing revision")
            key = (ref.layout, tuple(ref.insert_path), ref.handle)
            if key in source_keys:
                raise ValueError("Duplicate source identity")
            source_keys.add(key)
        for obj in self.semantic_objects:
            if not set(obj.entity_ids) <= entity_ids:
                raise ValueError("Dangling semantic source reference")
        for edge in self.edges:
            if edge.source == edge.target:
                raise ValueError("Self edges are not supported")
            if edge.graph == "semantic":
                if edge.source not in semantic_ids or edge.target not in entity_ids:
                    raise ValueError("Invalid represented_by edge")
            elif edge.source not in entity_ids or edge.target not in entity_ids:
                raise ValueError("Dangling topology/edit reference")
        return self


class Patch(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    patch_id: Identifier
    drawing_id: Identifier
    expected_revision: Digest
    operation: Literal["TRANSLATE_ENTITIES"]
    target_ids: list[Identifier] = Field(min_length=1)
    vector_mm: Point
    reason: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_targets(self):
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("Duplicate patch targets")
        if self.vector_mm == (0.0, 0.0, 0.0):
            raise ValueError("Zero translation has no effect")
        return self


class Change(Contract):
    entity_id: str
    before: Geometry
    after: Geometry


class PlanReport(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    patch_id: str
    status: Literal["simulation_passed", "rejected"]
    native_write_eligible: Literal[False] = False
    affected_ids: list[str]
    errors: list[str]
    warnings: list[str]
    changes: list[Change]
