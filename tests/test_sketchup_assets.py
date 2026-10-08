"""SketchUp model knowledge assets (0914 meeting model) -> sion-map-export/v1 -> GraphRAG."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.repository import seed_core_types
from sion_graphrag import build_custom_kg
from sion_ingestion.graph_export import convert_file
from sion_ingestion.map_import import MapExport, import_map_export
from sion_ingestion.sketchup_assets import (
    DEFAULTS,
    SketchUpAssetError,
    attach_sketchup_evidence,
    build_export,
    export_text,
    parse_guidelines,
    reachable_definitions,
)

ROOT = Path(__file__).resolve().parents[1]
PATHS = DEFAULTS["0914-meeting"]
DUMP_SHA256 = "33ebc367f6916e339fc9bc03a75a06403a7f37e4a6b8245e82b5c7e512a61bd6"
PROBE_SHA256 = "c7a26eaf9fe1424a56c46803eb75f964834d673c2f859abdce074d85ced042a8"
NS = "sketchup:0914-meeting"


def _build(**overrides) -> MapExport:
    paths = {**PATHS, **overrides}
    return build_export(
        paths["dump"],
        paths["classes"],
        paths["classification"],
        paths["guidelines"],
        namespace="0914-meeting",
        probe_path=paths["probe"],
    )


@pytest.fixture(scope="module")
def export() -> MapExport:
    return _build()


@pytest.fixture(scope="module")
def dump() -> dict:
    return json.loads(PATHS["dump"].read_text(encoding="utf-8"))


def _nodes(export: MapExport) -> dict:
    return {n.stable_key: n for n in export.nodes}


def test_sources_are_byte_identical_and_overlay_pins_dump():
    assert hashlib.sha256(PATHS["dump"].read_bytes()).hexdigest() == DUMP_SHA256
    assert hashlib.sha256(PATHS["probe"].read_bytes()).hexdigest() == PROBE_SHA256
    overlay = json.loads(PATHS["classification"].read_text(encoding="utf-8"))
    assert overlay["model_dump_sha256"] == DUMP_SHA256


def test_committed_export_matches_regeneration(export):
    assert PATHS["output"].read_text(encoding="utf-8") == export_text(export)
    data = json.loads(PATHS["output"].read_text(encoding="utf-8"))
    assert data["schema"] == "sion-map-export/v1"
    assert (data["expected_node_count"], data["expected_edge_count"]) == (len(export.nodes), len(export.edges))


def test_every_model_object_is_captured(export, dump):
    nodes = _nodes(export)
    kinds = Counter(n.properties.get("node_kind") for n in export.nodes)
    assert kinds["su_definition"] == len(dump["definitions"]) == 297
    assert kinds["su_tag"] == len(dump["layers"]) == 49
    assert kinds["su_material"] == len(dump["materials"]) == 130
    assert kinds["su_scene"] == len(dump["pages"]) == 3
    assert kinds["su_style"] == len(dump["styles"]) == 3
    assert kinds["su_section_plane"] == 1
    placements = [h for h in dump["hierarchy"] if h["depth"] <= 1]
    assert kinds["su_instance"] == len(placements) == 76
    assert len({h["pid"] for h in placements}) == len(placements)
    assert len(reachable_definitions(dump)) == 238
    # every definition node keeps its dump locator and sha
    for n in export.nodes:
        if n.properties.get("node_kind") == "su_definition":
            ev = n.properties["su_evidence"]
            assert ev["source_sha256"] == DUMP_SHA256 and ev["locator"].startswith("$.definitions[")
    assert nodes[f"{NS}:model"].properties["sketchup_version"] == "25.0.634"


def test_spot_facts_round_trip(export):
    nodes = _nodes(export)
    col = nodes[f"{NS}:def:col"]
    assert col.properties["bounds_size_mm"] == [480.0, 480.0, 4200.0] and col.properties["instances"] == 4
    assert col.properties["geometry_probe"]["arc_radii_mm"] == [240.0]
    assert nodes[f"{NS}:def:c1"].properties["instances"] == 47
    section = nodes[f"{NS}:section:1"]
    assert section.properties["offset_mm"] == pytest.approx(23411.7)
    obj = nodes[f"{NS}:obj:2004749"]
    assert obj.properties["material"].startswith("Polished Concrete") and obj.properties["layer"] == "Layer0"
    # '@win' (CAD convention) and 'WIN' stay distinct, readable keys
    assert nodes[f"{NS}:tag:at-win"].properties["tag_name"] == "@win"
    assert nodes[f"{NS}:tag:win"].properties["tag_name"] == "WIN"


def test_facts_are_verified_inferences_are_candidates(export):
    for e in export.edges:
        inferred = e.properties.get("candidate") is True
        if inferred:
            assert e.verification_state == "unverified" and e.source_kind in {"inferred", "document"}
        else:
            assert e.verification_state == "machine_verified" and e.confidence == 1.0
        assert e.properties.get("su_evidence", {}).get("locator")
    classified = [e for e in export.edges if e.properties.get("predicate") == "classified_as"]
    overlay = [e for e in classified if e.properties.get("candidate") is True]
    assert len(overlay) == 214 and len(classified) == 214 + (297 - 238)
    unused = [
        e
        for e in export.edges
        if e.target_stable_key == "sketchup:class:unused-definition" and e.relation_type_id == "IMPLEMENTS"
    ]
    assert len(unused) == 297 - 238 and all(e.verification_state == "machine_verified" for e in unused)


def test_guidelines_cover_every_assigned_class(export):
    guides = parse_guidelines(PATHS["guidelines"])
    assert len(guides) == 31 and [g["order"] for g in guides] == list(range(1, 32))
    covered = {cid for g in guides for cid in g["applies_to"]}
    overlay = json.loads(PATHS["classification"].read_text(encoding="utf-8"))
    assigned = {a["class"] for a in overlay["assignments"]} | {"unused-definition"}
    assert assigned <= covered
    nodes = _nodes(export)
    column_guide = nodes["sketchup:guide:column-beam"]
    assert column_guide.entity_type_id == "Document" and "[관측]" in column_guide.description
    edges = {(e.source_stable_key, e.relation_type_id, e.target_stable_key) for e in export.edges}
    assert ("sketchup:guide:column-beam", "REFERENCES", "sketchup:class:column") in edges
    assert ("sketchup:guide:column-beam", "DERIVED_FROM", f"{NS}:def:col") in edges
    assert ("sketchup:guide:column-beam", "USES", "tool:mcp:sketchup-mcp2") in edges


def test_bad_guideline_reference_is_rejected(tmp_path):
    text = PATHS["guidelines"].read_text(encoding="utf-8").replace('evidence="def:col,', 'evidence="def:없는정의,', 1)
    bad = tmp_path / "bad.md"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(SketchUpAssetError):
        _build(guidelines=bad)


def test_generic_converter_accepts_the_export():
    converted, report = convert_file(PATHS["output"])
    assert len(converted.nodes) == report.node_count and len(converted.edges) == report.edge_count
    assert {n.stable_key for n in converted.nodes} >= {f"{NS}:model", "sketchup:guide:overview"}


def test_import_attach_evidence_and_project_to_graphrag(export):
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        seed_core_types(session)
        result = import_map_export(session, export)
        assert result.created_nodes == len(export.nodes) and result.created_edges == len(export.edges)
        created = attach_sketchup_evidence(session, export, base_uri="file:///repo")
        with_evidence = [n for n in export.nodes if n.properties.get("su_evidence")]
        assert len(export.nodes) - len(with_evidence) == 3  # the three Tool nodes carry no model evidence
        assert created == len(with_evidence) + len(export.edges)
        assert attach_sketchup_evidence(session, export, base_uri="file:///repo") == 0  # idempotent
        kg = build_custom_kg(session)

    entities = {e["entity_name"]: e for e in kg["entities"]}
    assert len(entities) == len(export.nodes)
    guide = entities["sketchup:guide:column-beam"]["description"]
    assert "기둥" in guide and "docs/sketchup/MODELING-GUIDELINES.ko.md @ L" in guide
    col = entities[f"{NS}:def:col"]["description"]
    assert "data/sources/sketchup/0914-meeting/model_dump.json @ $.definitions[" in col
    assert any(r["src_id"] == f"{NS}:def:col" and r["tgt_id"] == "sketchup:class:column" for r in kg["relationships"])
