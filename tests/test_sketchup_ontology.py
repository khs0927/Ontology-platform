"""Per-object ontology overlay for the 0914 SketchUp model (block rule, assets, levels)."""

from __future__ import annotations

import json

from sion_ingestion.sketchup_assets import DEFAULTS, build_export
from sion_ingestion.sketchup_ontology import (
    BLOCK_CLASSES,
    HASHES,
    HIERARCHY,
    OBJECTS,
    OUTPUT,
    build_ontology,
    export_text,
    safe_rel,
)

D = DEFAULTS["0914-meeting"]


def _build(**kw):
    base = build_export(
        D["dump"],
        D["classes"],
        D["classification"],
        D["guidelines"],
        namespace="0914-meeting",
        probe_path=D["probe"],
        grouping_probe_path=D["grouping_probe"],
        grouping_doc_path=D["grouping_doc"],
    )
    cls = json.loads(D["classification"].read_text(encoding="utf-8"))
    kw.setdefault("hierarchy", json.loads(HIERARCHY.read_text(encoding="utf-8")))
    kw.setdefault("objects", json.loads(OBJECTS.read_text(encoding="utf-8")))
    kw.setdefault("hashes", json.loads(HASHES.read_text(encoding="utf-8")) if HASHES.exists() else None)
    kw.setdefault("hierarchy_ref", "data/sources/sketchup/0914-meeting/hierarchy.json")
    kw.setdefault("objects_ref", "data/sources/sketchup/0914-meeting/objects.json")
    _sup = HIERARCHY.parent / "classification.supplement.json"
    kw.setdefault("supplement", json.loads(_sup.read_text(encoding="utf-8")) if _sup.exists() else None)
    kw.setdefault("supplement_ref", "data/sources/sketchup/0914-meeting/classification.supplement.json")
    return build_ontology(base, classification=cls, **kw), cls


def test_committed_export_is_up_to_date_and_deterministic():
    exp, _ = _build()
    assert OUTPUT.read_text(encoding="utf-8") == export_text(exp)


def test_block_rule_collapses_entourage_children():
    exp, cls = _build()
    cls_of = {a["definition"]: a["class"] for a in cls["assignments"]}
    inst = [n for n in exp.nodes if n.properties.get("node_kind") == "su_instance"]
    roots = [tuple(n.properties["pid_path"]) for n in inst if n.properties.get("block_node")]
    assert roots
    for n in inst:
        p = tuple(n.properties["pid_path"])
        assert not any(len(p) > len(r) and p[: len(r)] == r for r in roots)
        if not n.properties.get("block_node"):
            assert cls_of.get(n.properties["definition_name"]) not in BLOCK_CLASSES or any(
                p[: len(r)] == r for r in roots
            )


def test_every_object_has_reloadable_asset_and_overlay_is_unverified():
    exp, _ = _build()
    keys = {n.stable_key: n for n in exp.nodes}
    has_asset = {e.source_stable_key for e in exp.edges if e.properties["predicate"] == "stored_as_asset"}
    for n in exp.nodes:
        p = n.properties
        if p.get("node_kind") == "su_instance" and (p["depth"] <= 1 or p.get("block_node")):
            assert n.stable_key in has_asset
    for e in exp.edges:
        if e.properties["predicate"] == "on_level":
            assert e.verification_state == "unverified"
        if e.properties["predicate"] == "on_level":
            assert e.properties["basis_ko"]
    assert all(not keys[k].properties.get("asset_path", "x").startswith(("C:", "/")) for k in keys)


def test_run2_manifest_paths_are_made_relative():
    assert safe_rel("C:/Users/example/su/out/objects/tree/a__1.skp") == "objects/tree/a__1.skp"
    assert safe_rel("C:\\Users\\example\\x.skp") == "x.skp"
    exp, _ = _build(
        objects={
            "objects": [
                {"pid": 30598, "file": "C:/Users/example/su/out/objects/site-container/s__30598.skp", "sha256": "ab"}
            ]
        }
    )
    a = [n for n in exp.nodes if n.properties.get("asset_path") == "objects/site-container/s__30598.skp"]
    assert a and a[0].properties["asset_state"] == "exported"


def test_roof_links_level_by_top_as_unverified_candidate():
    exp, _ = _build()
    tops = [e for e in exp.edges if e.properties["predicate"] == "on_level_by_top"]
    assert tops and all(e.verification_state == "unverified" and e.properties["basis_ko"] for e in tops)


def test_hashes_fill_asset_sha():
    exp, _ = _build()
    a = next(n for n in exp.nodes if n.properties.get("node_kind") == "su_asset")
    exp2, _ = _build(hashes={"files": [{"file": a.properties["asset_path"], "sha256": "f" * 64}]})
    assert next(n for n in exp2.nodes if n.stable_key == a.stable_key).properties["sha256"] == "f" * 64


def test_supplement_candidates_are_unverified():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sup = json.loads(
        (root / "data/sources/sketchup/0914-meeting/classification.supplement.json").read_text(encoding="utf-8")
    )
    assert len(sup["assignments"]) == 248
    assert all(a["verification_state"] == "unverified" and a["basis_ko"] for a in sup["assignments"])
    d = json.loads((root / "data/bootstrap/sketchup-0914-meeting.ontology.json").read_text(encoding="utf-8"))
    cands = [n for n in d["nodes"] if n["properties"].get("class_candidate")]
    assert cands and all(n["properties"]["class_candidate_state"] == "unverified" for n in cands)
