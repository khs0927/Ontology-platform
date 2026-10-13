"""Per-object SketchUp ontology overlay (0914 meeting model) -> ``sion-map-export/v1``.

Takes the base export from :mod:`sion_ingestion.sketchup_assets` and applies the user's rules:

* **Block rule** — trees, people, vehicles, planters, furniture, millwork and imported 3D
  entourage are remembered as *one* block node. Nested occurrences inside such a block are
  dropped (their geometry lives in the block's asset file, not in the graph).
* **Reloadable assets** — every kept top/second-level object and every block node is linked
  (``REFERENCES`` / ``stored_as_asset``) to an ``Artifact`` node for its exported ``.skp``
  (``objects.json`` manifest from ``scripts/sketchup/export_objects.rb``). Without a manifest,
  the planned path is recorded with ``asset_state = "planned"``.
* **Levels** — instances whose world min-Z sits on +5.0 / +10.2 / +14.6 m (±tolerance) get an
  inferred ``on_level`` candidate edge to a level ``Concept`` node.
* **Fresh hierarchy** — optional ``hierarchy.json`` (run2 dump) adds occurrences missing from
  the base dump as machine-verified containment facts.

All overlay judgements (block, level) are ``unverified`` candidates with ``basis_ko``; nothing
is auto-approved. Output is deterministic. Private absolute paths are reduced to relative ones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sion_ingestion.map_import import MapExport
from sion_ingestion.sketchup_assets import DEFAULTS, ROOT, build_export, export_text

NS = "0914-meeting"
BLOCK_CLASSES = ("tree", "person", "vehicle", "planter", "furniture", "counter-millwork", "imported-3d")
LEVELS_MM = {"L1": 5000.0, "L2": 10200.0, "L3": 14600.0}
LEVEL_TOL_MM = 400.0
TOP_LEVEL_CLASSES = ("roof",)
OUTPUT = ROOT / "data/bootstrap/sketchup-0914-meeting.ontology.json"
HIERARCHY = ROOT / "data/sources/sketchup/0914-meeting/hierarchy.json"
OBJECTS = ROOT / "data/sources/sketchup/0914-meeting/objects.json"
SUPPLEMENT = ROOT / "data/sources/sketchup/0914-meeting/classification.supplement.json"
HASHES = ROOT / "data/sources/sketchup/0914-meeting/objects_sha.json"
EXTRACTOR = "sion-sketchup-ontology/v1"
_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|/)")


def safe_rel(path: str | None) -> str | None:
    """Strip private absolute prefixes; keep the part from ``objects/`` (or the basename)."""
    if not path:
        return None
    p = path.replace("\\", "/")
    if "/objects/" in p:
        return "objects/" + p.split("/objects/", 1)[1]
    return p.rsplit("/", 1)[-1] if _ABS.match(p) else p


def _safe_name(n: str) -> str:
    return re.sub(r'[\\/:*?"<>|#~\s]+', "_", n)[:60]


def _ev(src: str, locator: str) -> dict[str, Any]:
    return {"source_file": src, "locator": locator, "skp_file": "0914_담당미팅.skp"}


def build_ontology(
    base: MapExport | dict[str, Any],
    *,
    classification: dict[str, Any],
    hierarchy: dict[str, Any] | None = None,
    objects: dict[str, Any] | None = None,
    hierarchy_ref: str = "hierarchy.json",
    objects_ref: str = "objects.json",
    hashes: dict[str, Any] | None = None,
    supplement: dict[str, Any] | None = None,
    supplement_ref: str = "classification.supplement.json",
) -> MapExport:
    data = base.model_dump(by_alias=True) if isinstance(base, MapExport) else json.loads(json.dumps(base))
    pfx = f"sketchup:{NS}"
    cls_of = {a["definition"]: a["class"] for a in classification["assignments"]}
    nodes: dict[str, dict[str, Any]] = {n["stable_key"]: n for n in data["nodes"]}
    edges: list[dict[str, Any]] = list(data["edges"])
    by_path: dict[tuple[int, ...], str] = {}
    for k, n in nodes.items():
        pp = n["properties"].get("pid_path") if n["properties"].get("node_kind") == "su_instance" else None
        if pp:
            by_path[tuple(pp)] = k

    def add_edge(src, rtype, tgt, predicate, ev, *, inferred, basis=None, conf=None, **props):
        key = f"{src}:{rtype}:{tgt}"
        if key in edge_keys:
            return
        edge_keys.add(key)
        p = {"predicate": predicate, **props, "su_evidence": ev}
        if inferred:
            p.update(candidate=True, extractor=EXTRACTOR, basis_ko=basis)
        edges.append(
            {
                "stable_key": key,
                "source_stable_key": src,
                "target_stable_key": tgt,
                "relation_type_id": rtype,
                "confidence": conf if inferred else 1.0,
                "verification_state": "unverified" if inferred else "machine_verified",
                "source_kind": "inferred" if inferred else "mcp",
                "ontology_version": None,
                "properties": p,
            }
        )

    edge_keys = {e["stable_key"] for e in edges}

    # 1) fresh hierarchy: add missing occurrences (facts)
    if hierarchy:
        pid_path: dict[int, tuple[int, ...]] = {}
        for i, h in enumerate(hierarchy["nodes"]):
            par = pid_path.get(h["parent_pid"], ()) if h.get("parent_pid") is not None else ()
            path = (*par, h["pid"])
            pid_path[h["pid"]] = path  # deeper pids repeat; last-seen parent is the DFS parent
            if path in by_path or h.get("inside_block"):
                continue
            key = f"{pfx}:{'obj' if len(path) <= 2 else 'occ'}:" + (
                str(path[-1]) if len(path) <= 2 else ".".join(map(str, path))
            )
            if key in nodes:
                by_path[path] = key
                continue
            label = h.get("name") or h.get("definition") or str(h["pid"])
            nodes[key] = {
                "stable_key": key,
                "entity_type_id": "Entity",
                "name": f"{label} @ {h.get('path', '')}"[:500],
                "category": "cad_bim",
                "external_uri": None,
                "ontology_version": None,
                "description": f"{h['depth'] + 1}단계 {h.get('type')} '{label}' (경로 {h.get('path')}, persistent_id {h['pid']}). 정의 {h.get('definition')}. 태그 {h.get('tag')}.",
                "properties": {
                    "node_kind": "su_instance",
                    "persistent_id": h["pid"],
                    "pid_path": list(path),
                    "depth": h["depth"],
                    "su_type": h.get("type"),
                    "instance_name": h.get("name", ""),
                    "definition_name": h.get("definition"),
                    "entity_path": h.get("path"),
                    "layer": h.get("tag"),
                    "material": h.get("material"),
                    "world_bounds_mm": h.get("world_bbox"),
                    "from_run2": True,
                    "su_evidence": _ev(hierarchy_ref, f"$.nodes[{i}]"),
                },
            }
            by_path[path] = key
            if len(path) > 1 and tuple(path[:-1]) in by_path:
                add_edge(
                    key,
                    "PART_OF",
                    by_path[tuple(path[:-1])],
                    "nested_in_instance",
                    _ev(hierarchy_ref, f"$.nodes[{i}]"),
                    inferred=False,
                )

    # 2) block rule: collapse entourage
    blocks = sorted(
        p for p, k in by_path.items() if cls_of.get(nodes[k]["properties"].get("definition_name")) in BLOCK_CLASSES
    )
    block_roots: list[tuple[int, ...]] = []
    for p in blocks:
        if not any(p[: len(r)] == r for r in block_roots):
            block_roots.append(p)
    drop: set[str] = set()
    for p, k in by_path.items():
        if any(len(p) > len(r) and p[: len(r)] == r for r in block_roots):
            drop.add(k)
    for r in block_roots:
        n = nodes[by_path[r]]
        c = cls_of[n["properties"]["definition_name"]]
        inner = sum(1 for p in by_path if len(p) > len(r) and p[: len(r)] == r)
        n["properties"].update(
            block_node=True,
            block_class=c,
            collapsed_children=inner,
            block_basis_ko=f"분류 '{c}'은(는) 블록 규칙 대상: 내부 형상은 그래프에 풀지 않고 자산 파일 하나로 기억한다(하위 {inner}개 생략).",
        )
    for k in drop:
        nodes.pop(k)
    edges = [e for e in edges if e["source_stable_key"] not in drop and e["target_stable_key"] not in drop]
    edge_keys = {e["stable_key"] for e in edges}
    by_path = {p: k for p, k in by_path.items() if k not in drop}

    # 3) levels
    for lid, z in LEVELS_MM.items():
        nodes[f"{pfx}:level:{lid}"] = {
            "stable_key": f"{pfx}:level:{lid}",
            "entity_type_id": "Concept",
            "name": f"레벨 {lid} (+{z / 1000:.1f} m 추정)",
            "category": "cad_bim",
            "external_uri": None,
            "ontology_version": None,
            "description": f"슬래브 상단 높이 +{z / 1000:.1f} m 부근에서 반복되는 수평 레벨(추정). 지음 규칙 레벨 이름은 사람 검토 후 확정.",
            "properties": {"node_kind": "su_level", "elevation_mm": z, "tolerance_mm": LEVEL_TOL_MM, "candidate": True},
        }
    for p, k in sorted(by_path.items()):
        wb = nodes[k]["properties"].get("world_bounds_mm") or {}
        zmin = (wb.get("min") or [None] * 3)[2]
        if zmin is None:
            continue
        for lid, z in LEVELS_MM.items():
            if abs(zmin - z) <= LEVEL_TOL_MM:
                add_edge(
                    k,
                    "PART_OF",
                    f"{pfx}:level:{lid}",
                    "on_level",
                    nodes[k]["properties"].get("su_evidence", {}),
                    inferred=True,
                    conf=0.6,
                    basis=f"월드 최소 Z {zmin:,.1f} mm가 레벨 +{z / 1000:.1f} m에서 ±{LEVEL_TOL_MM:.0f} mm 안",
                )

    # 3b) roofs: top face at a level (roof slabs hang below the level line)
    for p, k in sorted(by_path.items()):
        props = nodes[k]["properties"]
        if cls_of.get(props.get("definition_name")) not in TOP_LEVEL_CLASSES:
            continue
        wb = props.get("world_bounds_mm") or {}
        if not wb.get("max"):
            continue
        ztop, zmin = wb["max"][2], wb["min"][2]
        for lid, z in LEVELS_MM.items():
            if abs(ztop - z) <= LEVEL_TOL_MM and abs(zmin - z) > LEVEL_TOL_MM:
                add_edge(
                    k,
                    "PART_OF",
                    f"{pfx}:level:{lid}",
                    "on_level_by_top",
                    props.get("su_evidence", {}),
                    inferred=True,
                    conf=0.4,
                    basis=f"지붕 분류: 월드 최대 Z {ztop:,.1f} mm가 레벨 +{z / 1000:.1f} m에서 ±{LEVEL_TOL_MM:.0f} mm 안"
                    f"(최소 Z {zmin:,.1f} mm는 레벨 밖이라 상단 기준으로 연결)",
                )

    # 3c) supplement: candidate classes for unclassified occurrences (never approved here)
    sup = {a["pid"]: (i, a) for i, a in enumerate((supplement or {}).get("assignments", []))}
    for k in by_path.values():
        props = nodes[k]["properties"]
        hit = sup.get(props.get("persistent_id"))
        if not hit or props.get("definition_name") in cls_of:
            continue
        i, a = hit
        props.update(
            class_candidate=a["class"],
            class_candidate_confidence=a["confidence"],
            class_candidate_state="unverified",
            class_candidate_source_kind="inferred",
            class_candidate_basis_ko=a["basis_ko"],
            class_candidate_evidence=_ev(supplement_ref, f"$.assignments[{i}]"),
        )

    # 4) assets
    sha_of = {f["file"]: f["sha256"] for f in (hashes or {}).get("files", [])}
    manifest = {}
    if objects:
        for i, o in enumerate(objects.get("objects", [])):
            manifest[o["pid"] if len(str(o.get("id", ""))) else o["pid"]] = (i, o)
    for p, k in sorted(by_path.items()):
        props = nodes[k]["properties"]
        if not (len(p) <= 2 or props.get("block_node")):
            continue
        dname = props.get("definition_name") or ""
        c = cls_of.get(dname) or props.get("class_candidate") or "unclassified"
        hit = manifest.get(p[-1])
        if hit:
            i, o = hit
            rel, sha, state, ev = (
                safe_rel(o.get("file")),
                o.get("sha256"),
                ("exported" if o.get("file") else "failed"),
                _ev(objects_ref, f"$.objects[{i}]"),
            )
        else:
            rel, sha, state, ev = (
                f"objects/{c}/{_safe_name(dname)}__{p[-1]}.skp",
                None,
                "planned",
                props.get("su_evidence", {}),
            )
        if rel is None:
            continue
        sha = sha or sha_of.get(rel)
        akey = f"{pfx}:asset:{hashlib.sha256(rel.encode()).hexdigest()[:16]}"
        if akey not in nodes:
            nodes[akey] = {
                "stable_key": akey,
                "entity_type_id": "Artifact",
                "name": f"자산 {rel}",
                "category": "cad_bim",
                "external_uri": None,
                "ontology_version": None,
                "description": f"정의 '{dname}'을(를) 단독 .skp로 저장한 재사용 자산(상대경로, SION_STORAGE_ROOT 기준). 상태 {state}.",
                "properties": {
                    "node_kind": "su_asset",
                    "asset_path": rel,
                    "sha256": sha,
                    "asset_state": state,
                    "definition_name": dname,
                    "class_guess": c,
                },
            }
        add_edge(k, "REFERENCES", akey, "stored_as_asset", ev, inferred=False)

    data["nodes"] = sorted(nodes.values(), key=lambda n: n["stable_key"])
    data["edges"] = sorted(edges, key=lambda e: e["stable_key"])
    data["expected_node_count"], data["expected_edge_count"] = len(data["nodes"]), len(data["edges"])
    keys = set(nodes)
    for e in data["edges"]:
        if e["source_stable_key"] not in keys or e["target_stable_key"] not in keys:
            raise ValueError(f"dangling edge {e['stable_key']}")
    return MapExport.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sion_ingestion.sketchup_ontology")
    ap.add_argument("--hierarchy")
    ap.add_argument("--objects")
    ap.add_argument("--classification")
    ap.add_argument("-o", "--output", default=str(OUTPUT))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    d = DEFAULTS[NS]
    base = build_export(
        d["dump"],
        d["classes"],
        d["classification"],
        d["guidelines"],
        namespace=NS,
        probe_path=d["probe"],
        grouping_probe_path=d["grouping_probe"],
        grouping_doc_path=d["grouping_doc"],
    )

    def load(p):
        return json.loads(Path(p).read_text(encoding="utf-8-sig")) if p else None

    exp = build_ontology(
        base,
        classification=load(a.classification or d["classification"]),
        hierarchy=load(a.hierarchy or (HIERARCHY if HIERARCHY.exists() else None)),
        objects=load(a.objects or (OBJECTS if OBJECTS.exists() else None)),
        hashes=load(HASHES if HASHES.exists() else None),
        supplement=load(SUPPLEMENT if SUPPLEMENT.exists() else None),
        supplement_ref=f"data/sources/sketchup/{NS}/classification.supplement.json",
        hierarchy_ref=f"data/sources/sketchup/{NS}/hierarchy.json",
        objects_ref=f"data/sources/sketchup/{NS}/objects.json",
    )
    text = export_text(exp)
    out = Path(a.output)
    if a.check:
        ok = out.exists() and out.read_text(encoding="utf-8") == text
        print(json.dumps({"nodes": len(exp.nodes), "edges": len(exp.edges), "up_to_date": ok}))
        return 0 if ok else 1
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"nodes": len(exp.nodes), "edges": len(exp.edges), "written": str(out.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
