"""Build `sion-bim-asset/1` cards for every definition and instance of a SketchUp model.

Usage: python scripts/sketchup/build_bim_cards.py [--model 0914-meeting] [--check]

Inputs  : data/sources/sketchup/<model>/{model_dump,hierarchy,objects,objects_sha,classification*}.json
Outputs : data/assets/sketchup/<model>/cards/{def-*.json,inst-*.json}, cards.jsonl, coverage.json
          data/assets/sketchup/recipes/<class>.json (class-level Korean recipe templates)
All mappings are inferred (review_state=unverified). Local absolute paths are never emitted.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "sources" / "sketchup"
OUT = ROOT / "data" / "assets" / "sketchup"
SCHEMA = "sion-bim-asset/1"
ASSET_STORE = "SketchUp-Assets/ontology-objects"  # Google Drive (My Drive) relative root
LEVELS = [("GL ±0", 0.0), ("1 FL +5000", 5000.0), ("2 FL +10200", 10200.0), ("RF TOS +14600", 14600.0)]
LEVEL_TOL = 600.0

# class -> (IfcEntity, PredefinedType, bSDD IFC class URI, proposed zium tag, block?, method)
IFC = {
    "site-container": ("IfcSite", None, "Layer0→CAD-참조", False, "cad-import"),
    "terrain": ("IfcGeographicElement", "TERRAIN", "@3D-대지", False, "faces-sandbox"),
    "retaining-wall": ("IfcWall", "RETAININGWALL", "옹벽", False, "extrude"),
    "paving": ("IfcSlab", "PAVING", "@3D-대지", False, "extrude"),
    "parking-deck": ("IfcSlab", "FLOOR", "@3D-대지", False, "extrude"),
    "parking-stall": ("IfcAnnotation", None, "@3D-대지", True, "2d-block"),
    "road-plan-surface": ("IfcGeographicElement", "USERDEFINED", "도로계획", False, "cad-import"),
    "exterior-stair": ("IfcStair", "STRAIGHT_RUN_STAIR", "@stair", False, "array"),
    "handrail": ("IfcRailing", "HANDRAIL", "@stair", False, "follow-me"),
    "glass-railing": ("IfcRailing", "GUARDRAIL", "@stair", False, "extrude"),
    "building": ("IfcBuilding", None, "A-본동", False, "assembly"),
    "floor-slab": ("IfcSlab", "FLOOR", "A-본동", False, "extrude"),
    "wall": ("IfcWall", "STANDARD", "A-본동", False, "extrude"),
    "curtain-wall": ("IfcCurtainWall", None, "@win", False, "array"),
    "door": ("IfcDoor", "DOOR", "@door", True, "component"),
    "window-louver": ("IfcWindow", "WINDOW", "@win", False, "array"),
    "column": ("IfcColumn", "COLUMN", "S-STEEL COLUMN", True, "extrude"),
    "beam": ("IfcBeam", "BEAM", "S-STEEL COLUMN", False, "extrude"),
    "roof": ("IfcRoof", "FLAT_ROOF", "A-본동", False, "extrude"),
    "interior-stair": ("IfcStair", "STRAIGHT_RUN_STAIR", "@stair", False, "array"),
    "counter-millwork": ("IfcFurniture", "USERDEFINED", "@FUR", True, "component"),
    "furniture": ("IfcFurniture", "CHAIR", "@FUR", True, "component"),
    "planter": ("IfcGeographicElement", "USERDEFINED", "Trees 3D", True, "component"),
    "tree": ("IfcGeographicElement", "VEGETATION", "Trees 3D", True, "component"),
    "person": ("IfcBuildingElementProxy", "USERDEFINED", "@FUR", True, "component"),
    "annotation": ("IfcAnnotation", None, "@DIM", False, "2d"),
    "marker": ("IfcAnnotation", None, "WIP", False, "2d"),
    "cad-reference": ("IfcAnnotation", None, "CAD-참조", False, "cad-import"),
    "imported-3d": ("IfcBuildingElementProxy", "USERDEFINED", "@FUR", True, "component"),
    "unused-definition": ("IfcBuildingElementProxy", "NOTDEFINED", "(purge 후보)", False, "none"),
    "unclassified": ("IfcBuildingElementProxy", "NOTDEFINED", "Layer0", False, "unknown"),
}
METHOD_KO = {
    "cad-import": "CAD(dwg) 가져오기 컴포넌트를 호스트로 두고 하위 그룹으로 부위를 나눔",
    "faces-sandbox": "등고선/점에서 면을 만들고(샌드박스·create_face) 단차별 그룹으로 묶음",
    "extrude": "평면 윤곽을 그린 뒤 push/pull로 두께·높이만큼 돌출",
    "follow-me": "단면(원/사각)을 경로를 따라 Follow-Me로 쓸어 만듦",
    "array": "단위 부재(단·멀리언·패널) 하나를 그룹으로 만든 뒤 복사 배열(Move+Ctrl, xN)",
    "assembly": "층·부위 하위 그룹을 중첩해 조립한 건물 컨테이너",
    "component": "외부/라이브러리 컴포넌트를 한 블럭으로 배치(내부 분해 금지)",
    "2d-block": "2D 기호 블럭을 바닥에 배치",
    "2d": "선·문자 등 2D 작업 표식",
    "none": "사용되지 않는 정의(purge 대상)",
    "unknown": "형상 근거 부족 — 사람 검토 필요",
}
BLOCK_CLASSES = {"tree", "person", "furniture", "planter", "counter-millwork", "imported-3d"}
MAT_RULES = [
    (r"glass|glaz|유리|translucent|window", "glass"),
    (r"concrete|콘크리트|cement", "concrete"),
    (r"brick|벽돌", "masonry-brick"),
    (r"travertine|stone|marble|granite|quartz|석", "stone"),
    (r"wood|oak|timber|walnut|plywood|목|veneer", "wood"),
    (r"metal|steel|alum|iron|chrome|brass|금속|철", "metal"),
    (r"grass|vegetation|leaf|bark|tree|foliage|잔디", "vegetation"),
    (r"fabric|leather|cloth|skin|hair|textile", "textile-or-figure"),
    (r"water|물", "water"),
    (r"asphalt|paving|tile|타일", "paving-tile"),
    (r"<auto>", "auto-generated (purge 후보)"),
]
NAME_SAFE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def basename(p):
    if not p:
        return None
    return re.split(r"[\\/]", str(p))[-1] or None


def mat_category(name: str) -> str:
    low = (name or "").lower()
    for pat, cat in MAT_RULES:
        if re.search(pat, low):
            return cat
    return "paint-or-colour"


def level_for(zmin):
    if zmin is None:
        return None
    best = min(LEVELS, key=lambda lv: abs(lv[1] - zmin))
    return {"name": best[0], "elevation_mm": best[1], "base_z_mm": round(zmin, 1),
            "matched": abs(best[1] - zmin) <= LEVEL_TOL}


def r1(x):
    return None if x is None else round(float(x), 1)


def params_from_size(size, count):
    if not size:
        return {"count": count}
    x, y, z = (float(v) for v in size)
    return {"length_mm": r1(max(x, y)), "width_mm": r1(min(x, y)), "height_mm": r1(z),
            "thickness_mm": r1(min(x, y, z)), "count": count}


def guides(doc_dir: Path):
    out = defaultdict(list)
    rx = re.compile(r'<!-- sion-guide id="([^"]+)"[^>]*?applies_to="([^"]+)"(?:[^>]*?tools="([^"]*)")?')
    for f in sorted(doc_dir.glob("*.md")):
        for m in rx.finditer(f.read_text(encoding="utf-8")):
            for c in m.group(2).split(","):
                out[c.strip()].append({"guide": m.group(1), "doc": f"docs/sketchup/{f.name}",
                                       "tools": [t for t in (m.group(3) or "").split(",") if t]})
    return out


def build(model: str):
    d = SRC / model
    dump = load(d / "model_dump.json")
    hier = load(d / "hierarchy.json")["nodes"]
    objs = load(d / "objects.json")["objects"]
    sha = {f["file"]: f for f in load(d / "objects_sha.json")["files"]}
    cls_def = {a["definition"]: a for a in load(d / "classification.json")["assignments"]}
    sup = load(d / "classification.supplement.json")["assignments"]
    cls_pid = {a["pid"]: a for a in sup}
    mats = {m["name"]: m for m in dump["materials"]}
    gd = guides(ROOT / "docs" / "sketchup")
    file_by_pid = {o["pid"]: o["file"] for o in objs}
    nodes_by_def = defaultdict(list)
    for n in hier:
        nodes_by_def[n["definition"]].append(n)
    for a in sup:  # supplement fills definitions lacking a definition-level class
        cls_def.setdefault(a["definition"], a)

    def material_map(names):
        out = []
        for nm in sorted(n for n in names if n):
            m = mats.get(nm) or mats.get(nm.strip("[]")) or {}
            tex = m.get("texture") or {}
            out.append({"sketchup_material": nm, "bim_material_category": mat_category(nm),
                        "colour_rgb": (m.get("color") or [None, None, None])[:3],
                        "alpha": m.get("alpha"), "texture_file": basename(tex.get("filename")),
                        "texture_size_mm": [tex.get("width_mm"), tex.get("height_mm")] if tex else None})
        return out

    def asset_file(rel):
        if not rel or rel not in sha:
            return None
        png = rel[:-4] + ".png"
        return {"store": "google-drive", "root": f"{ASSET_STORE}/{model}", "skp": rel,
                "sha256": sha[rel]["sha256"], "bytes": sha[rel]["bytes"],
                "thumbnail": png if png in sha else None,
                "thumbnail_sha256": sha[png]["sha256"] if png in sha else None}

    def mapping(cls):
        ent, pdt, tag, blk, method = IFC.get(cls, IFC["unclassified"])
        return ent, pdt, tag, blk, method

    def recipe(cls, nested, child_defs, kind):
        ent, pdt, tag, blk, method = mapping(cls)
        return {"method": method, "method_ko": METHOD_KO[method],
                "nesting": nested, "sketchup_kind": kind, "child_definitions": child_defs,
                "guides": gd.get(cls, []),
                "ruby_hint": ("scripts/sketchup/regroup_0914.rb (태그·레벨·블럭 재구성, 기본 미리보기)"
                              if cls != "unused-definition" else "purge_unused (사람 승인 후)"),
                "class_recipe": f"data/assets/sketchup/recipes/{cls}.json"}

    cards, def_ids = [], {}
    for df in dump["definitions"]:
        def_ids[df["name"]] = f"su-def:{model}:{df['guid']}"
    inner_defs = {k for k, ns in nodes_by_def.items() if ns and all(n.get("inside_block") for n in ns)}
    children = defaultdict(list)
    for i, n in enumerate(hier):
        children[n.get("parent_pid")].append(i)

    def inner_of(pid):
        out, stack = [], list(children.get(pid, []))
        while stack:
            i = stack.pop()
            out.append(i)
            stack += children.get(hier[i]["pid"], [])
        return out
    for df in sorted(dump["definitions"], key=lambda x: x["guid"]):
        name = df["name"]
        if name in inner_defs:
            continue  # 사용자 규칙: 블럭 내부 정의는 별도 자산이 아님(블럭 카드에서 참조)
        a = cls_def.get(name)
        nodes = nodes_by_def.get(name, [])
        if a:
            cls, conf, basis = a["class"], a.get("confidence"), a["basis_ko"]
        elif df.get("used_instances", 0) == 0:
            cls, conf, basis = "unused-definition", 0.7, f"사용 인스턴스 0개(instances={df.get('instances')}) — 루트에서 도달 불가"
        elif nodes and nodes[0].get("class_guess"):
            cls, conf, basis = nodes[0]["class_guess"], 0.4, "계층 노드의 class_guess 상속"
        else:
            cls, conf, basis = "unclassified", 0.0, "분류 근거 없음 — 사람 검토 필요"
        ent, pdt, tag, blk, method = mapping(cls)
        files = [file_by_pid[n["pid"]] for n in nodes if n["pid"] in file_by_pid]
        layers = df.get("instance_layers") or {}
        cards.append({
            "schema": SCHEMA, "card_kind": "definition", "asset_id": def_ids[name], "model": model,
            "source": {"definition": name, "guid": "su-guid:" + df["guid"], "kind": df["kind"],
                       "source_file": basename(df.get("path")), "instances": df.get("instances"),
                       "used_instances": df.get("used_instances"),
                       "instance_pids": sorted(n["pid"] for n in nodes)},
            "class": cls,
            "ifc": {"entity": ent, "predefined_type": pdt,
                    "bsdd_uri": f"https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3/class/{ent}"},
            "parameters": {**params_from_size(df.get("bounds_size"), df.get("used_instances")),
                           "face_area_m2": df.get("face_area_m2"), "entity_counts": df.get("entity_counts", {})},
            "level": level_for(nodes[0]["world_bbox"]["min"][2]) if nodes else None,
            "tag": {"current": sorted(layers) or ["Layer0"], "inner_layers": sorted(df.get("layers_used") or {}),
                    "proposed_zium": tag},
            "materials": material_map(set(df.get("materials_used") or {}) | {n.get("material") for n in nodes}),
            "recipe": recipe(cls, "definition", sorted(df.get("child_definitions") or {}), df["kind"]),
            "block": bool(blk or cls in BLOCK_CLASSES or any(n.get("block_node") for n in nodes)),
            "asset_file": asset_file(sorted(files)[0]) if files else None,
            "provenance": {"dump": f"data/sources/sketchup/{model}/model_dump.json",
                           "classification": "classification.json" if name in cls_def and "pid" not in cls_def[name] else
                           ("classification.supplement.json" if a else "build_bim_cards.py rule"),
                           "generator": "scripts/sketchup/build_bim_cards.py"},
            "review_state": "unverified", "confidence": conf, "basis_ko": basis,
        })
    for idx, n in enumerate(hier):
        if n.get("inside_block"):
            continue  # 블럭 = 객체 1개 = 카드 1개
        a = cls_pid.get(n["pid"])
        dcard = next(c for c in cards if c["asset_id"] == def_ids[n["definition"]])
        cls = (a or {}).get("class") or n.get("class_guess") or dcard["class"]
        ent, pdt, tag, blk, method = mapping(cls)
        bb = n.get("world_bbox") or {}
        cards.append({
            "schema": SCHEMA, "card_kind": "instance", "asset_id": f"su-inst:{model}:{n['pid']}@{idx}", "model": model,
            "definition_ref": def_ids[n["definition"]],
            "source": {"pid": n["pid"], "occurrence": idx, "hierarchy_locator": f"$.nodes[{idx}]", "definition": n["definition"], "path": n["path"], "depth": n["depth"],
                       "type": n["type"], "parent_pid": n.get("parent_pid"), "name": n.get("name") or None},
            "class": cls,
            "ifc": {"entity": ent, "predefined_type": pdt,
                    "bsdd_uri": f"https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3/class/{ent}"},
            "parameters": {**params_from_size(bb.get("size"), 1), "world_bbox_mm": bb,
                           "faces_recursive": n.get("faces_recursive"), "transformation": n.get("transformation")},
            "level": level_for((bb.get("min") or [None] * 3)[2]),
            "tag": {"current": [n.get("tag") or "Layer0"], "proposed_zium": tag},
            "materials": material_map({n.get("material")}),
            "recipe": recipe(cls, "inside-block" if n.get("inside_block") else f"depth-{n['depth']}",
                             [], n["type"]),
            "block": bool(n.get("block_node") or (blk and not n.get("inside_block"))),
            "block_contents": ({"inner_occurrences": len(inner_of(n["pid"])),
                                "inner_definitions": sorted({hier[i]["definition"] for i in inner_of(n["pid"])}),
                                "note_ko": "블럭은 하나의 객체로만 기억 — 내부 부품은 별도 카드·분석 없음"}
                               if n.get("block_node") else None),
            "asset_file": asset_file(file_by_pid.get(n["pid"])) or dcard["asset_file"],
            "provenance": {"hierarchy": f"data/sources/sketchup/{model}/hierarchy.json",
                           "classification": "classification.supplement.json" if a else "hierarchy class_guess / definition card",
                           "generator": "scripts/sketchup/build_bim_cards.py"},
            "review_state": "unverified", "confidence": (a or {}).get("confidence", dcard["confidence"]),
            "basis_ko": (a or {}).get("basis_ko") or f"정의 카드 {dcard['asset_id']} 분류 상속: {dcard['basis_ko']}",
        })
    return cards, dump, hier, gd


def recipes(cards, gd, labels):
    by = defaultdict(list)
    for c in cards:
        if c["card_kind"] == "definition":
            by[c["class"]].append(c)
    out = {}
    for cls in sorted(set(labels) | set(by)):
        cs = by.get(cls, [])
        ent, pdt, tag, blk, method = IFC.get(cls, IFC["unclassified"])

        def rng(k):
            v = [c["parameters"].get(k) for c in cs if c["parameters"].get(k) is not None]
            return None if not v else {"min": min(v), "median": round(statistics.median(v), 1), "max": max(v), "n": len(v)}
        mcat = defaultdict(int)
        for c in cs:
            for m in c["materials"]:
                mcat[m["bim_material_category"]] += 1
        out[cls] = {
            "schema": "sion-bim-recipe/1", "class": cls, "label_ko": labels.get(cls, cls),
            "ifc": {"entity": ent, "predefined_type": pdt}, "proposed_zium_tag": tag,
            "block": bool(blk or cls in BLOCK_CLASSES),
            "how_to_make_ko": [
                METHOD_KO[method],
                "최상위/2단계 인스턴스에만 의미 태그를 붙이고 내부 형상은 Layer0으로 둔다",
                "기준 레벨(GL/1FL/2FL/RF) 바닥 높이에 원점을 맞추고 정의 원점은 부재 좌하단",
                "블럭 객체는 내부를 분해하지 않고 한 컴포넌트로 저장·재사용" if blk or cls in BLOCK_CLASSES
                else "건물 형태가 달라지면 윤곽만 새로 그리고 두께·높이 파라미터 범위를 재사용",
            ],
            "typical_params_mm": {k: rng(k) for k in ("length_mm", "width_mm", "height_mm", "thickness_mm")},
            "material_categories": dict(sorted(mcat.items())),
            "guides": gd.get(cls, []),
            "examples": [c["asset_id"] for c in cs[:10]], "definition_count": len(cs),
            "source_model": "0914-meeting", "review_state": "unverified",
        }
    return out


def dumps(o):
    return json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="0914-meeting")
    ap.add_argument("--check", action="store_true", help="fail if outputs are stale")
    a = ap.parse_args(argv)
    cards, dump, hier, gd = build(a.model)
    labels = {c["id"]: c["label_ko"] for c in load(SRC / "object-classes.json")["classes"]}
    files = {}
    base = OUT / a.model
    for c in cards:
        stem = ("def-" + c["source"]["guid"].removeprefix("su-guid:")) if c["card_kind"] == "definition" else f"inst-{c['source']['occurrence']:04d}-{c['source']['pid']}"
        files[base / "cards" / f"{stem}.json"] = dumps(c)
    files[base / "cards.jsonl"] = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cards)
    nd = sum(c["card_kind"] == "definition" for c in cards)
    ni = len(cards) - nd
    n_inner_def = sum(all(x.get("inside_block") for x in ns) for ns in
                      [[n for n in hier if n["definition"] == d["name"]] for d in dump["definitions"]] if ns)
    n_inner_occ = sum(bool(n.get("inside_block")) for n in hier)
    exp = len(dump["definitions"]) - n_inner_def + len(hier) - n_inner_occ
    cov = {"model": a.model, "rule_ko": "블럭(나무·사람·가구 등)=객체 1개=카드 1개, 블럭 내부 정의·부품은 카드 없음",
           "definitions_total": len(dump["definitions"]), "definitions_inside_blocks_only": n_inner_def,
           "definition_cards": nd, "occurrences_total": len(hier), "occurrences_inside_blocks": n_inner_occ,
           "instance_cards": ni, "expected_cards": exp,
           "coverage_pct": round(100.0 * (nd + ni) / exp, 2),
           "with_asset_file": sum(bool(c["asset_file"]) for c in cards),
           "block_cards": sum(c["block"] for c in cards),
           "occurrence_note": "인스턴스 카드는 hierarchy 노드(occurrence) 단위; 같은 pid가 여러 부모 경로에 나타날 수 있음",
           "classes": {k: sum(c["class"] == k for c in cards) for k in sorted({c["class"] for c in cards})}}
    files[base / "coverage.json"] = dumps(cov)
    for cls, r in recipes(cards, gd, labels).items():
        files[OUT / "recipes" / f"{cls}.json"] = dumps(r)
    stale = [p for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
    if a.check:
        if stale:
            print(f"stale: {len(stale)} files, e.g. {stale[0]}", file=sys.stderr)
            return 1
        print("up to date", json.dumps(cov))
        return 0
    for p, t in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    print(json.dumps(cov))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
