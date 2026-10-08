"""SketchUp model knowledge assets -> ``sion-map-export/v1``.

Builds graph nodes/edges for GraphRAG from three inputs:

* a read-only SketchUp model dump (``scripts/sketchup/dump_model.rb``; definitions, hierarchy,
  tags, materials, scenes, styles, section planes),
* an object-class vocabulary plus a per-model classification overlay (human/agent-authored,
  every assignment is an *inferred* candidate with its basis written down),
* a Korean modeling-guideline markdown whose ``##`` sections are retrievable chunks
  (``<!-- sion-guide ... -->`` metadata links each chunk to classes, tools and evidence).

Rules:

* Facts read from the model (containment, instance-of, tag, material, scene/style) are
  ``machine_verified`` with ``source_kind = "mcp"`` (the dump was taken through an MCP server).
* Classifications and guideline links are ``unverified`` candidates (``properties.candidate``),
  so they show up on ``/review``.
* Every node and edge carries ``properties.su_evidence`` = source file (repo-relative), its
  SHA-256 and a JSON/markdown locator. :func:`attach_sketchup_evidence` turns these into
  ``evidence`` rows, which the GraphRAG projection prints with each chunk.
* Output is deterministic (no timestamps), so the committed export can be regenerated and
  compared byte-for-byte.

Only the standard library is used (plus the repo's pydantic contract).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sion_ingestion.map_import import MapExport

EXTRACTOR = "sion-sketchup-assets/v1"
CLASSES_SCHEMA = "sion-sketchup-object-classes/v1"
CLASSIFICATION_SCHEMA = "sion-sketchup-classification/v1"
ROOT = Path(__file__).resolve().parents[3]

TOOL_NODES = {
    "sketchup": ("Tool", "SketchUp", "SketchUp 데스크톱 모델러. 이 모델은 SketchUp 25.0.634에서 열려 있었다."),
    "sketchup-mcp2": (
        "Tool",
        "sketchup-mcp2 (SketchUp MCP 서버)",
        "SketchUp MCP 서버. 선형 단위 mm 명시(create_component·transform_component의 position은 bbox 최소점). "
        "도구: get_model_info, list_components, get_component_info, find_components, list_layers, get_selection, "
        "create_component, transform_component, set_material, create_layer, boolean_operation, export_scene, "
        "get_viewport_screenshot(SketchUp 2026 필요), eval_ruby, undo, delete_component, chamfer_edge, fillet_edge, "
        "create_mortise_tenon, create_dovetail, create_finger_joint, get_version.",
    ),
    "hueflow-sketchup": (
        "Tool",
        "Hueflow SketchUp MCP",
        "Hueflow SketchUp MCP 서버. 도구: get_model_info, list_layers, list_materials, list_entities, "
        "list_components, create_group, create_box, create_face, create_edge, create_circle, create_arc, create_polygon, "
        "create_roof_truss, push_pull, "
        "follow_me, move_entity, rotate_entity, scale_entity, create_component, place_component, execute_ruby. "
        "create_face 설명상 좌표 단위가 'SketchUp 기본 단위(모델이 metric이 아니면 inch)'이고 create_roof_truss는 "
        "span을 feet, spacing·overhang·origin을 inch로 받으므로, 치수가 중요하면 execute_ruby에서 .mm 변환을 명시한다.",
    ),
}
TOOL_ALIASES = {"sketchup-mcp2": "sketchup-mcp2", "hueflow": "hueflow-sketchup", "sketchup": "sketchup"}

KIND_KO = {"group": "그룹", "component": "컴포넌트", "image": "이미지"}


class SketchUpAssetError(ValueError):
    """Inputs are inconsistent (hash mismatch, unknown class, broken reference)."""


# --------------------------------------------------------------------------- helpers


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _slug(text: str) -> str:
    text = re.sub(r"^@", "at-", text.strip())  # keep CAD '@wall' distinct from 'WALL'
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", text).strip("-").lower()
    return slug[:120] or hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class _Keys:
    """Readable, collision-free slugs (LightRAG uses the stable_key as entity name)."""

    def __init__(self) -> None:
        self._by_kind: dict[str, dict[str, str]] = defaultdict(dict)
        self._used: dict[str, set[str]] = defaultdict(set)

    def get(self, kind: str, raw: str) -> str:
        known = self._by_kind[kind].get(raw)
        if known is not None:
            return known
        slug = _slug(raw)
        if slug in self._used[kind]:
            slug = f"{slug}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"
        self._used[kind].add(slug)
        self._by_kind[kind][raw] = slug
        return slug


def _fmt(v: float) -> str:
    return f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)


def _size(values: list[float] | None) -> str:
    return "×".join(_fmt(v) for v in values) + " mm" if values else "크기 없음"


def _top(counter: dict[str, int], n: int = 5) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


GUIDE_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
META_RE = re.compile(r"<!--\s*sion-guide\s+(?P<body>.*?)-->", re.DOTALL)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_guidelines(path: Path) -> list[dict[str, Any]]:
    """Split the guideline markdown into ``##`` chunks with their ``sion-guide`` metadata."""
    text = path.read_text(encoding="utf-8")
    heads = list(GUIDE_RE.finditer(text))
    chunks = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[head.end() : end]
        meta = META_RE.search(body)
        if meta is None:
            raise SketchUpAssetError(f"guideline section {head.group('title')!r} has no sion-guide metadata")
        attrs = dict(ATTR_RE.findall(meta.group("body")))
        if "id" not in attrs:
            raise SketchUpAssetError(f"guideline section {head.group('title')!r} has no id")
        content = (body[: meta.start()] + body[meta.end() :]).strip()
        start_line = text.count("\n", 0, head.start()) + 1
        end_line = text.count("\n", 0, end.__index__() if isinstance(end, int) else end)
        chunks.append(
            {
                "id": attrs["id"],
                "order": int(attrs.get("order", i + 1)),
                "kind": attrs.get("kind", "guideline"),
                "title": head.group("title").strip(),
                "applies_to": [x for x in attrs.get("applies_to", "").split(",") if x],
                "tools": [x for x in attrs.get("tools", "").split(",") if x],
                "evidence": [x for x in attrs.get("evidence", "").split(",") if x],
                "after": [x for x in attrs.get("after", "").split(",") if x],
                "text": content,
                "locator": f"L{start_line}-L{end_line}",
            }
        )
    ids = [c["id"] for c in chunks]
    if len(ids) != len(set(ids)):
        raise SketchUpAssetError("duplicate guideline ids")
    return chunks


def reachable_definitions(dump: dict[str, Any]) -> set[str]:
    """Definitions reachable from the model root (placed somewhere in the live tree)."""
    by_name = {d["name"]: d for d in dump["definitions"]}
    live: set[str] = set()
    stack = [n["definition"] for n in dump["hierarchy"] if n["depth"] == 0]
    while stack:
        name = stack.pop()
        if name in live or name not in by_name:
            continue
        live.add(name)
        stack.extend(by_name[name]["child_definitions"])
    return live


# --------------------------------------------------------------------------- builder


class _Graph:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._node_keys: set[str] = set()
        self._edge_keys: set[str] = set()

    def node(self, key: str, etype: str, name: str, category: str, description: str, properties: dict[str, Any]) -> str:
        if key in self._node_keys:
            raise SketchUpAssetError(f"duplicate node {key}")
        self._node_keys.add(key)
        self.nodes.append(
            {
                "stable_key": key,
                "entity_type_id": etype,
                "name": name[:500],
                "category": category,
                "description": description,
                "properties": properties,
            }
        )
        return key

    def edge(
        self,
        src: str,
        rtype: str,
        tgt: str,
        *,
        predicate: str,
        evidence: dict[str, Any],
        inferred: bool = False,
        confidence: float | None = None,
        source_kind: str | None = None,
        **props: Any,
    ) -> None:
        if src not in self._node_keys or tgt not in self._node_keys:
            raise SketchUpAssetError(f"dangling edge {src} -{rtype}-> {tgt}")
        key = f"{src}:{rtype}:{tgt}"
        if key in self._edge_keys:
            raise SketchUpAssetError(f"duplicate edge {key}")
        self._edge_keys.add(key)
        properties: dict[str, Any] = {"predicate": predicate, **{k: v for k, v in props.items() if v is not None}}
        properties["su_evidence"] = evidence
        if inferred:
            properties["candidate"] = True
            properties["extractor"] = EXTRACTOR
        self.edges.append(
            {
                "stable_key": key,
                "source_stable_key": src,
                "target_stable_key": tgt,
                "relation_type_id": rtype,
                "confidence": confidence if confidence is not None else (None if inferred else 1.0),
                "verification_state": "unverified" if inferred else "machine_verified",
                "source_kind": source_kind or ("inferred" if inferred else "mcp"),
                "properties": properties,
            }
        )


def build_export(
    dump_path: str | Path,
    classes_path: str | Path,
    classification_path: str | Path,
    guidelines_path: str | Path,
    *,
    namespace: str,
    probe_path: str | Path | None = None,
) -> MapExport:
    dump_path, classes_path = Path(dump_path), Path(classes_path)
    classification_path, guidelines_path = Path(classification_path), Path(guidelines_path)
    dump = json.loads(dump_path.read_text(encoding="utf-8-sig"))
    vocab = json.loads(classes_path.read_text(encoding="utf-8"))
    overlay = json.loads(classification_path.read_text(encoding="utf-8"))
    guides = parse_guidelines(guidelines_path)
    probe = json.loads(Path(probe_path).read_text(encoding="utf-8-sig")) if probe_path else {}
    if vocab.get("schema") != CLASSES_SCHEMA:
        raise SketchUpAssetError(f"{classes_path.name}: expected schema {CLASSES_SCHEMA}")
    if overlay.get("schema") != CLASSIFICATION_SCHEMA:
        raise SketchUpAssetError(f"{classification_path.name}: expected schema {CLASSIFICATION_SCHEMA}")

    dump_sha = _sha256(dump_path)
    if overlay.get("model_dump_sha256") not in (None, dump_sha):
        raise SketchUpAssetError("classification was written for a different model dump (sha256 mismatch)")
    dump_rel = _rel(dump_path)
    guide_rel, guide_sha = _rel(guidelines_path), _sha256(guidelines_path)
    overlay_rel, overlay_sha = _rel(classification_path), _sha256(classification_path)
    probe_rel = _rel(Path(probe_path)) if probe_path else None
    probe_sha = _sha256(Path(probe_path)) if probe_path else None

    model = dump["model"]
    skp_file = Path(str(model.get("path") or model["title"]).replace("\\", "/")).name
    ns = namespace
    keys = _Keys()
    g = _Graph()

    def ev(locator: str, **extra: Any) -> dict[str, Any]:
        return {"source_file": dump_rel, "source_sha256": dump_sha, "locator": locator, "skp_file": skp_file, **extra}

    def guide_ev(chunk: dict[str, Any]) -> dict[str, Any]:
        return {"source_file": guide_rel, "source_sha256": guide_sha, "locator": f"{chunk['locator']} #{chunk['id']}"}

    def overlay_ev(index: int) -> dict[str, Any]:
        return {"source_file": overlay_rel, "source_sha256": overlay_sha, "locator": f"$.assignments[{index}]"}

    k_model = f"sketchup:{ns}:model"
    k_dump = f"sketchup:{ns}:dump"

    def k_def(name: str) -> str:
        return f"sketchup:{ns}:def:{keys.get('def', name)}"

    def k_tag(name: str) -> str:
        return f"sketchup:{ns}:tag:{keys.get('tag', name)}"

    def k_mat(name: str) -> str:
        return f"sketchup:{ns}:mat:{keys.get('mat', name)}"

    def k_obj(pid: int) -> str:
        return f"sketchup:{ns}:obj:{pid}"

    def k_class(cid: str) -> str:
        return f"sketchup:class:{cid}"

    def k_guide(gid: str) -> str:
        return f"sketchup:guide:{gid}"

    def k_tool(tid: str) -> str:
        return f"tool:mcp:{tid}" if tid != "sketchup" else "tool:sketchup"

    definitions = dump["definitions"]
    live = reachable_definitions(dump)
    def_index = {d["name"]: i for i, d in enumerate(definitions)}
    first_node: dict[str, dict[str, Any]] = {}
    for node in dump["hierarchy"]:
        first_node.setdefault(node["definition"], node)
    parents: dict[str, set[str]] = defaultdict(set)
    for d in definitions:
        for child in d["child_definitions"]:
            parents[child].add(d["name"])

    # ---- tools
    for tid, (etype, name, desc) in TOOL_NODES.items():
        g.node(k_tool(tid), etype, name, "ai_automation", desc, {"node_kind": "tool"})

    # ---- model + dump
    bounds = model["bounds"]
    units = model["units_options"]
    shadow = model["shadow_info"]
    model_desc = (
        f"SketchUp 모델 '{model['title']}'({skp_file}). SketchUp {dump['_meta']['sketchup_version']}. "
        f"단위 mm(LengthUnit={units.get('LengthUnit')}, 정밀도 {units.get('LengthPrecision')}, 길이 스냅 1 mm, 각도 스냅 {units.get('SnapAngle')}°, "
        f"면적 m²·체적 m³). 전체 범위 {_size(bounds['size'])}, 최소점 {bounds['min']}, 최대점 {bounds['max']}. "
        f"최상위 엔터티 {model['top_level_count']}개({', '.join(f'{k} {v}' for k, v in sorted(model['top_level_types'].items()))}), "
        f"정의 {model['definitions_count']}개(루트에서 도달 {len(live)}개, 미도달 {len(definitions) - len(live)}개), "
        f"태그 {model['layers_count']}개, 재질 {model['materials_count']}개, 장면 {model['pages_count']}개, 스타일 {model['styles_count']}개. "
        f"위치 {shadow.get('City')}/{shadow.get('Country')} 위도 {shadow.get('Latitude')} 경도 {shadow.get('Longitude')}, "
        f"지오레퍼런스 사용 안 함({model.get('georeferenced')}). 저장되지 않은 변경 있음(modified={model.get('modified')})."
    )
    g.node(
        k_model,
        "Artifact",
        f"SketchUp 모델 {model['title']}",
        "cad_bim",
        model_desc,
        {
            "node_kind": "su_model",
            "skp_file": skp_file,
            "skp_path": model.get("path"),
            "sketchup_version": dump["_meta"]["sketchup_version"],
            "units_options": units,
            "shadow_info": shadow,
            "bounds_mm": bounds,
            "top_level_types": model["top_level_types"],
            "counts": {
                "definitions": len(definitions),
                "definitions_live": len(live),
                "layers": model["layers_count"],
                "materials": model["materials_count"],
                "pages": model["pages_count"],
                "styles": model["styles_count"],
                "hierarchy_nodes": len(dump["hierarchy"]),
            },
            "totals_definition_level": dump.get("totals_definition_level", {}),
            "su_evidence": ev("$.model"),
        },
    )
    g.node(
        k_dump,
        "Dataset",
        f"SketchUp 모델 덤프 {skp_file} (읽기 전용 추출)",
        "data_validation",
        f"{skp_file}를 읽기 전용 Ruby(scripts/sketchup/dump_model.rb, MCP execute_ruby)로 추출한 JSON. "
        f"정의 {len(definitions)}개, 계층 노드 {len(dump['hierarchy'])}개(잘림 {dump.get('hierarchy_truncated', 0)}), "
        f"태그 {len(dump['layers'])}개, 재질 {len(dump['materials'])}개, 장면 {len(dump['pages'])}개. 추출 시각 {dump['_meta'].get('dumped_at')}.",
        {
            "node_kind": "su_dump",
            "source_file": dump_rel,
            "content_hash": f"sha256:{dump_sha}",
            "byte_size": dump_path.stat().st_size,
            "mime_type": "application/json",
            "extractor": dump["_meta"].get("tool"),
            "geometry_probe": {"source_file": probe_rel, "source_sha256": probe_sha} if probe_rel else None,
            "su_evidence": ev("$._meta"),
        },
    )
    g.edge(k_dump, "EXTRACTED_FROM", k_model, predicate="extracted_from", evidence=ev("$._meta"))
    g.edge(k_model, "USES", k_tool("sketchup"), predicate="authored_in", evidence=ev("$._meta.sketchup_version"))
    g.edge(k_dump, "DERIVED_FROM", k_tool("hueflow-sketchup"), predicate="extracted_via_mcp", evidence=ev("$._meta"))

    # ---- object classes
    class_ids = set()
    for i, c in enumerate(vocab["classes"]):
        class_ids.add(c["id"])
        g.node(
            k_class(c["id"]),
            "Concept",
            f"{c['label_ko']} ({c['label_en']})",
            c.get("category") or "cad_bim",
            f"SketchUp 객체 클래스 '{c['label_ko']}'. {c['description_ko']}",
            {
                "node_kind": "su_object_class",
                "class_id": c["id"],
                "label_en": c["label_en"],
                "su_evidence": {
                    "source_file": _rel(classes_path),
                    "source_sha256": _sha256(classes_path),
                    "locator": f"$.classes[{i}]",
                },
            },
        )

    # ---- tags
    tag_live: dict[str, int] = defaultdict(int)
    for d in definitions:
        if d["name"] in live:
            for t, n in d["layers_used"].items():
                tag_live[t] += n
    for i, layer in enumerate(dump["layers"]):
        usage = layer.get("usage_by_type") or {}
        total = layer.get("usage_total", 0)
        state = (
            "미사용(엔터티 0)"
            if total == 0
            else ("살아 있는 정의에서 사용" if tag_live.get(layer["name"]) else "미사용 정의 안에서만 사용(CAD 잔여)")
        )
        g.node(
            k_tag(layer["name"]),
            "Concept",
            f"태그 {layer['name']}",
            "cad_bim",
            f"SketchUp 태그(레이어) '{layer['name']}'. 표시 {layer['visible']}, 색 RGBA {layer['color']}, 선 스타일 {layer.get('line_style')}. "
            f"엔터티 {total}개({', '.join(f'{k} {v}' for k, v in sorted(usage.items())) or '없음'}), 루트에서 도달하는 정의 안 사용 {tag_live.get(layer['name'], 0)}개. 상태: {state}.",
            {
                "node_kind": "su_tag",
                "tag_name": layer["name"],
                "visible": layer["visible"],
                "color_rgba": layer["color"],
                "line_style": layer.get("line_style"),
                "usage_by_type": usage,
                "usage_total": total,
                "usage_live": tag_live.get(layer["name"], 0),
                "at_prefix": layer["name"].startswith("@"),
                "su_evidence": ev(f"$.layers[{i}]", persistent_id=layer.get("persistent_id")),
            },
        )
        g.edge(k_tag(layer["name"]), "PART_OF", k_model, predicate="tag_of_model", evidence=ev(f"$.layers[{i}]"))

    # ---- materials
    for i, mat in enumerate(dump["materials"]):
        tex = mat.get("texture")
        usage = mat.get("usage_by_type") or {}
        tex_txt = (
            f"텍스처 {tex['filename']} ({_fmt(tex['width_mm'])}×{_fmt(tex['height_mm'])} mm)" if tex else "텍스처 없음"
        )
        g.node(
            k_mat(mat["name"]),
            "Concept",
            f"재질 {mat['name']}",
            "content_assets",
            f"SketchUp 재질 '{mat['name']}'. 색 RGB {mat['color']}, 불투명도 {mat['alpha']}, {tex_txt}. "
            f"사용 {mat.get('usage_total', 0)}회({', '.join(f'{k} {v}' for k, v in sorted(usage.items())) or '미사용'}).",
            {
                "node_kind": "su_material",
                "material_name": mat["name"],
                "color_rgb": mat["color"],
                "alpha": mat["alpha"],
                "texture": tex,
                "usage_by_type": usage,
                "usage_total": mat.get("usage_total", 0),
                "auto_from_cad": mat["name"].startswith("<auto>"),
                "su_evidence": ev(f"$.materials[{i}]"),
            },
        )
        g.edge(k_mat(mat["name"]), "PART_OF", k_model, predicate="material_of_model", evidence=ev(f"$.materials[{i}]"))

    # ---- styles, scenes, section planes
    for i, st in enumerate(dump["styles"]):
        g.node(
            f"sketchup:{ns}:style:{keys.get('style', st['name'])}",
            "Concept",
            f"스타일 {st['name']}",
            "cad_bim",
            f"SketchUp 스타일 '{st['name']}'. {st.get('description')}. 선택됨 {st.get('selected')}.",
            {"node_kind": "su_style", "su_evidence": ev(f"$.styles[{i}]")},
        )
        g.edge(
            f"sketchup:{ns}:style:{keys.get('style', st['name'])}",
            "PART_OF",
            k_model,
            predicate="style_of_model",
            evidence=ev(f"$.styles[{i}]"),
        )
    for i, pg in enumerate(dump["pages"]):
        cam = pg.get("camera") or {}
        key = f"sketchup:{ns}:scene:{i + 1}"
        g.node(
            key,
            "Concept",
            f"장면 {pg['name']}",
            "cad_bim",
            f"SketchUp 장면 '{pg['name']}'. 스타일 {pg.get('style')}, 카메라 eye {cam.get('eye')} → target {cam.get('target')}, "
            f"원근 {cam.get('perspective')} FOV {cam.get('fov')}°. 저장 항목: 카메라 {pg['use_camera']}, 숨긴 태그 {pg['use_hidden_layers']}, "
            f"스타일 {pg['use_style']}, 단면 {pg['use_section_planes']}. 숨긴 태그 {pg.get('hidden_layers') or '없음'}. "
            f"선택된 장면 {dump.get('selected_page') == pg['name']}.",
            {
                "node_kind": "su_scene",
                "camera": cam,
                "hidden_layers": pg.get("hidden_layers"),
                "su_evidence": ev(f"$.pages[{i}]"),
            },
        )
        g.edge(key, "PART_OF", k_model, predicate="scene_of_model", evidence=ev(f"$.pages[{i}]"))
        if pg.get("style"):
            g.edge(
                key,
                "USES",
                f"sketchup:{ns}:style:{keys.get('style', pg['style'])}",
                predicate="uses_style",
                evidence=ev(f"$.pages[{i}].style"),
            )
        for t in pg.get("hidden_layers") or []:
            g.edge(key, "REFERENCES", k_tag(t), predicate="hides_tag", evidence=ev(f"$.pages[{i}].hidden_layers"))
    for i, sp in enumerate(dump.get("section_planes", [])):
        a, b, c, dval = sp["plane"]
        key = f"sketchup:{ns}:section:{i + 1}"
        g.node(
            key,
            "Concept",
            f"단면 {sp.get('name')}",
            "cad_bim",
            f"SketchUp 단면 평면 '{sp.get('name')}'({sp['in_def']}), 활성 {sp['active']}. 평면식 {a}x+{b}y+{c}z{dval:+} = 0 (d는 inch). "
            f"법선 ({a}, {b}, {c}), 원점에서 {_fmt(-dval * 25.4)} mm.",
            {
                "node_kind": "su_section_plane",
                "plane_inch": sp["plane"],
                "offset_mm": round(-dval * 25.4, 1),
                "su_evidence": ev(f"$.section_planes[{i}]"),
            },
        )
        g.edge(key, "PART_OF", k_model, predicate="section_of_model", evidence=ev(f"$.section_planes[{i}]"))

    # ---- definitions
    for i, d in enumerate(definitions):
        name = d["name"]
        key = k_def(name)
        is_live = name in live
        ec = d["entity_counts"]
        node = first_node.get(name)
        wb = node["world_bounds"] if node else None
        mats = _top(d["materials_used"], 4)
        tags = {t: n for t, n in d["layers_used"].items()}
        geo = probe.get(name)
        parts = [
            f"SketchUp {KIND_KO.get(d['kind'], d['kind'])} 정의 '{name}'.",
            f"인스턴스 {d['instances']}개(배치됨 {d.get('used_instances')}), 루트 도달 {'예' if is_live else '아니오(미사용)'}.",
            f"정의 크기 {_size(d.get('bounds_size'))}, 면 {ec.get('Face', 0)}, 모서리 {ec.get('Edge', 0)}, 하위 그룹 {ec.get('Group', 0)}, 하위 컴포넌트 {ec.get('ComponentInstance', 0)}, 면적 합 {d.get('face_area_m2')} m².",
        ]
        if wb:
            parts.append(f"첫 배치 위치({node['path']}): 월드 최소점 {wb['min']} mm, 월드 크기 {_size(wb['size'])}.")
        if mats:
            parts.append("내부 재질: " + ", ".join(f"{m} {n}" for m, n in mats) + ".")
        if d.get("instance_layers"):
            parts.append(
                "인스턴스 태그: "
                + ", ".join(f"{t} {n}" for t, n in sorted(d["instance_layers"].items(), key=lambda kv: str(kv[0])))
                + "."
            )
        non0 = {t: n for t, n in tags.items() if t != "Layer0"}
        if non0:
            parts.append("내부 엔터티 태그(Layer0 외): " + ", ".join(f"{t} {n}" for t, n in _top(non0, 8)) + ".")
        if parents.get(name):
            parts.append("상위 정의: " + ", ".join(sorted(parents[name])[:6]) + ".")
        if d["child_definitions"]:
            parts.append("하위 정의: " + ", ".join(f"{c} ×{n}" for c, n in _top(d["child_definitions"], 8)) + ".")
        if geo:
            if geo.get("horizontal_levels"):
                lv = [z for z, _ in geo["horizontal_z_area_m2"]]
                parts.append(f"수평면 레벨(정의 좌표, mm) {len(lv)}개: {lv[:12]}{' …' if len(lv) > 12 else ''}.")
            if geo.get("sloped_faces_by_angle_deg"):
                ang = sorted(float(a) for a in geo["sloped_faces_by_angle_deg"])
                parts.append(f"경사면 각도 범위 {ang[0]}°~{ang[-1]}°.")
            if geo.get("arc_radii_mm"):
                parts.append(f"호 반경 {geo['arc_radii_mm']} mm.")
        if d.get("description") and d["description"] != name:
            parts.append(f"설명: {d['description'][:200]}")
        g.node(
            key,
            "Concept",
            f"{name} (SketchUp {KIND_KO.get(d['kind'], d['kind'])} 정의)",
            "cad_bim",
            " ".join(parts),
            {
                "node_kind": "su_definition",
                "definition_name": name,
                "su_kind": d["kind"],
                "guid": d["guid"],
                "instances": d["instances"],
                "used_instances": d.get("used_instances"),
                "live": is_live,
                "bounds_size_mm": d.get("bounds_size"),
                "first_world_bounds_mm": wb,
                "first_path": node["path"] if node else None,
                "entity_counts": ec,
                "face_area_m2": d.get("face_area_m2"),
                "edges_only_2d": ec.get("Face", 0) == 0 and ec.get("Edge", 0) > 0,
                "layers_used": tags,
                "instance_layers": d.get("instance_layers"),
                "materials_used": d["materials_used"],
                "behavior": d.get("behavior"),
                "attribute_dictionaries": sorted(d.get("attributes", {}).keys()),
                "geometry_probe": geo,
                "su_evidence": ev(f"$.definitions[{i}]", guid=d["guid"]),
            },
        )
    for i, d in enumerate(definitions):
        key = k_def(d["name"])
        g.edge(key, "PART_OF", k_model, predicate="defined_in_model", evidence=ev(f"$.definitions[{i}]"))
        for child, count in d["child_definitions"].items():
            g.edge(
                k_def(child),
                "PART_OF",
                key,
                predicate="nested_in_definition",
                evidence=ev(f"$.definitions[{i}].child_definitions"),
                count=count,
            )
        tag_counts: dict[str, dict[str, int]] = defaultdict(dict)
        for t, n in d["layers_used"].items():
            if t != "Layer0":
                tag_counts[t]["entities"] = n
        for t, n in (d.get("instance_layers") or {}).items():
            if t:
                tag_counts[t]["instances"] = n
        for t, counts in sorted(tag_counts.items()):
            g.edge(
                key, "USES", k_tag(t), predicate="uses_tag", evidence=ev(f"$.definitions[{i}].layers_used"), **counts
            )
        for m, n in sorted(d["materials_used"].items()):
            g.edge(
                key,
                "USES",
                k_mat(m),
                predicate="uses_material",
                evidence=ev(f"$.definitions[{i}].materials_used"),
                faces_and_edges=n,
            )

    # ---- placements: every top-level and second-level group/component instance
    for i, n in enumerate(dump["hierarchy"]):
        if n["depth"] > 1:
            continue
        key = k_obj(n["pid"])
        wb = n["world_bounds"]
        tr = n["transform"]
        label = n["name"] or n["definition"]
        cc = n["child_counts"]
        desc = (
            f"{'최상위' if n['depth'] == 0 else '2단계'} {('컴포넌트 인스턴스' if n['type'] == 'ComponentInstance' else '그룹')} '{label}' "
            f"(경로 {n['path']}, persistent_id {n['pid']}). 정의 {n['definition']}. 태그 {n['layer']}, 인스턴스 재질 {n['material'] or '없음'}. "
            f"월드 최소점 {wb['min'] if wb else None} mm, 월드 크기 {_size(wb['size'] if wb else None)}. 원점 {tr['origin']} mm, 축척 {tr['scale']}, Z 회전 {tr['rot_z_deg']}°. "
            f"직접 하위: {', '.join(f'{k} {v}' for k, v in sorted(cc.items())) or '없음'}."
        )
        g.node(
            key,
            "Entity",
            f"{label} @ {n['path']}",
            "cad_bim",
            desc,
            {
                "node_kind": "su_instance",
                "persistent_id": n["pid"],
                "depth": n["depth"],
                "su_type": n["type"],
                "instance_name": n["name"],
                "definition_name": n["definition"],
                "entity_path": n["path"],
                "layer": n["layer"],
                "material": n["material"],
                "transform": tr,
                "world_bounds_mm": wb,
                "child_counts": cc,
                "su_evidence": ev(f"$.hierarchy[{i}]", persistent_id=n["pid"], entity_path=n["path"]),
            },
        )
        loc = f"$.hierarchy[{i}]"
        parent = k_model if n["depth"] == 0 else k_obj(n["parent_pid"])
        g.edge(
            key, "PART_OF", parent, predicate="placed_in" if n["depth"] == 0 else "nested_in_instance", evidence=ev(loc)
        )
        g.edge(key, "REFERENCES", k_def(n["definition"]), predicate="instance_of", evidence=ev(loc))
        if n["layer"]:
            g.edge(key, "USES", k_tag(n["layer"]), predicate="placed_on_tag", evidence=ev(loc))
        if n["material"]:
            g.edge(key, "USES", k_mat(n["material"]), predicate="painted_with_material", evidence=ev(loc))

    # ---- classification (inferred) + unused (fact)
    unused = k_class("unused-definition")
    for i, d in enumerate(definitions):
        if d["name"] not in live:
            g.edge(
                k_def(d["name"]),
                "IMPLEMENTS",
                unused,
                predicate="classified_as",
                evidence=ev(f"$.definitions[{i}]"),
                basis_ko="모델 루트에서 도달하지 않는 정의(배치 경로 없음)",
            )
    classified: dict[str, str] = {}
    for i, item in enumerate(overlay["assignments"]):
        name, cid = item["definition"], item["class"]
        if name not in def_index:
            raise SketchUpAssetError(f"classification references unknown definition {name!r}")
        if cid not in class_ids:
            raise SketchUpAssetError(f"classification uses unknown class {cid!r}")
        classified[name] = cid
        g.edge(
            k_def(name),
            "IMPLEMENTS",
            k_class(cid),
            predicate="classified_as",
            evidence=overlay_ev(i),
            inferred=True,
            confidence=float(item["confidence"]),
            basis_ko=item["basis_ko"],
            model_evidence=ev(f"$.definitions[{def_index[name]}]"),
        )

    # ---- guidelines
    k_flow = "sketchup:workflow:architectural-site-model"
    g.node(
        k_flow,
        "Workflow",
        "SketchUp 건축·대지 모델 작성 워크플로(0914 모델 기반)",
        "cad_bim",
        "대지·옹벽·주차장·건물·내부·조경을 가진 SketchUp 건축 모델을 그리는 단계별 지침 묶음. "
        "각 단계는 sketchup:guide:* 문서 청크이며 DEPENDS_ON 엣지가 선행 단계를 가리킨다. "
        f"근거 모델 {skp_file}.",
        {
            "node_kind": "su_workflow",
            "guide_count": len(guides),
            "su_evidence": {"source_file": guide_rel, "source_sha256": guide_sha, "locator": "L1"},
        },
    )
    g.edge(
        k_flow,
        "DERIVED_FROM",
        k_model,
        predicate="derived_from_model",
        evidence={"source_file": guide_rel, "source_sha256": guide_sha, "locator": "L1"},
        inferred=True,
        confidence=0.8,
        source_kind="document",
    )
    guide_ids = {c["id"] for c in guides}
    for c in guides:
        key = k_guide(c["id"])
        g.node(
            key,
            "Document",
            f"[SketchUp 지침 {c['order']:02d}] {c['title']}",
            "ai_automation" if c["kind"] in {"mcp", "agent"} else "cad_bim",
            c["text"],
            {
                "node_kind": "su_guideline_chunk",
                "guide_id": c["id"],
                "order": c["order"],
                "guide_kind": c["kind"],
                "applies_to": c["applies_to"],
                "tools": c["tools"],
                "language": "ko",
                "su_evidence": guide_ev(c),
            },
        )
    for c in guides:
        key = k_guide(c["id"])
        gev = guide_ev(c)
        g.edge(
            key,
            "PART_OF",
            k_flow,
            predicate="step_of_workflow",
            evidence=gev,
            inferred=True,
            confidence=1.0,
            source_kind="document",
            order=c["order"],
        )
        for prev in c["after"]:
            if prev not in guide_ids:
                raise SketchUpAssetError(f"guide {c['id']} follows unknown guide {prev}")
            g.edge(
                key,
                "DEPENDS_ON",
                k_guide(prev),
                predicate="after_step",
                evidence=gev,
                inferred=True,
                confidence=1.0,
                source_kind="document",
            )
        for cid in c["applies_to"]:
            if cid not in class_ids:
                raise SketchUpAssetError(f"guide {c['id']} applies to unknown class {cid}")
            g.edge(
                key,
                "REFERENCES",
                k_class(cid),
                predicate="applies_to_class",
                evidence=gev,
                inferred=True,
                confidence=0.9,
                source_kind="document",
            )
        tools_seen: set[str] = set()
        for tool in c["tools"]:
            server, _, tool_name = tool.partition(".")
            tid = TOOL_ALIASES.get(server)
            if tid is None:
                raise SketchUpAssetError(f"guide {c['id']} names unknown MCP server {server}")
            if tid in tools_seen:
                continue
            tools_seen.add(tid)
            names = sorted(
                {t.partition(".")[2] for t in c["tools"] if TOOL_ALIASES.get(t.partition(".")[0]) == tid and "." in t}
            )
            g.edge(
                key,
                "USES",
                k_tool(tid),
                predicate="executed_with_tool",
                evidence=gev,
                inferred=True,
                confidence=0.9,
                source_kind="document",
                tool_names=names or None,
            )
        for ref in c["evidence"]:
            kind, _, value = ref.partition(":")
            if kind == "def":
                if value not in def_index:
                    raise SketchUpAssetError(f"guide {c['id']} cites unknown definition {value}")
                target = k_def(value)
            elif kind == "obj":
                target = k_obj(int(value))
            elif kind == "tag":
                target = k_tag(value)
            elif kind == "mat":
                target = k_mat(value)
            elif kind in {"scene", "section"}:
                target = f"sketchup:{ns}:{kind}:{value}"
            elif kind == "model":
                target = k_model
            else:
                raise SketchUpAssetError(f"guide {c['id']} has bad evidence ref {ref}")
            g.edge(
                key,
                "DERIVED_FROM",
                target,
                predicate="cites_model_evidence",
                evidence=gev,
                inferred=True,
                confidence=0.9,
                source_kind="document",
            )

    export = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": f"sketchup-assets:{ns}:{skp_file}#sha256={dump_sha[:16]}",
            "expected_node_count": len(g.nodes),
            "expected_edge_count": len(g.edges),
            "nodes": g.nodes,
            "edges": g.edges,
        }
    )
    return export


def export_text(export: MapExport) -> str:
    return json.dumps(export.model_dump(by_alias=True), ensure_ascii=False, indent=1) + "\n"


def attach_sketchup_evidence(session, export: MapExport, *, base_uri: str | None = None) -> int:
    """One evidence row per node and per edge from ``properties.su_evidence`` (idempotent)."""
    from sion_api import models
    from sqlalchemy import select

    base = base_uri or ROOT.as_uri()
    created = 0

    def add(*, entity_id=None, relation_id=None, evidence: dict[str, Any], verification_state: str, confidence):
        nonlocal created
        uri = f"{base.rstrip('/')}/{evidence['source_file']}"
        locator = evidence["locator"]
        column = models.Evidence.entity_id if entity_id is not None else models.Evidence.relation_id
        target = entity_id if entity_id is not None else relation_id
        exists = session.scalar(
            select(models.Evidence).where(
                column == target, models.Evidence.source_uri == uri, models.Evidence.source_locator == locator
            )
        )
        if exists is not None:
            return
        excerpt = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        session.add(
            models.Evidence(
                entity_id=entity_id,
                relation_id=relation_id,
                source_uri=uri,
                source_locator=locator,
                excerpt_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                confidence=confidence,
                verification_state=verification_state,
                extractor=EXTRACTOR,
                properties={"su_evidence": evidence, "kind": "sketchup-model"},
            )
        )
        created += 1

    for node in export.nodes:
        row = session.scalar(select(models.Entity).where(models.Entity.stable_key == node.stable_key))
        evidence = node.properties.get("su_evidence")
        if row is not None and evidence:
            add(entity_id=row.id, evidence=evidence, verification_state="machine_verified", confidence=1.0)
    for edge in export.edges:
        row = session.scalar(select(models.Relation).where(models.Relation.stable_key == edge.stable_key))
        evidence = edge.properties.get("su_evidence")
        if row is not None and evidence:
            add(
                relation_id=row.id,
                evidence=evidence,
                verification_state=edge.verification_state,
                confidence=edge.confidence,
            )
    session.commit()
    return created


# --------------------------------------------------------------------------- CLI

DEFAULTS = {
    "0914-meeting": {
        "dump": ROOT / "data/sources/sketchup/0914-meeting/model_dump.json",
        "probe": ROOT / "data/sources/sketchup/0914-meeting/geometry_probe.json",
        "classes": ROOT / "data/sources/sketchup/object-classes.json",
        "classification": ROOT / "data/sources/sketchup/0914-meeting/classification.json",
        "guidelines": ROOT / "docs/sketchup/MODELING-GUIDELINES.ko.md",
        "output": ROOT / "data/bootstrap/sketchup-0914-meeting.json",
    }
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sion_ingestion.sketchup_assets", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "import"):
        p = sub.add_parser(name)
        p.add_argument("--namespace", default="0914-meeting")
        for opt in ("dump", "probe", "classes", "classification", "guidelines"):
            p.add_argument(f"--{opt}")
        if name == "build":
            p.add_argument("-o", "--output")
            p.add_argument("--check", action="store_true", help="fail if the committed export differs")
        else:
            p.add_argument("--database-url", required=True)
    args = parser.parse_args(argv)
    defaults = DEFAULTS.get(args.namespace, {})

    def pick(opt: str):
        value = getattr(args, opt, None)
        return Path(value) if value else defaults.get(opt)

    export = build_export(
        pick("dump"),
        pick("classes"),
        pick("classification"),
        pick("guidelines"),
        namespace=args.namespace,
        probe_path=pick("probe"),
    )
    summary = {"nodes": len(export.nodes), "edges": len(export.edges)}
    if args.command == "build":
        out = Path(args.output) if args.output else defaults.get("output")
        text = export_text(export)
        if args.check:
            same = out is not None and out.exists() and out.read_text(encoding="utf-8") == text
            print(json.dumps({**summary, "up_to_date": same}, ensure_ascii=False))
            return 0 if same else 1
        if out is None:
            sys.stdout.write(text)
        else:
            out.write_text(text, encoding="utf-8")
            print(json.dumps({**summary, "written": _rel(out)}, ensure_ascii=False))
        return 0

    from sion_ingestion.map_import import import_map_export
    from sion_ingestion.relations_cli import _session

    with _session(args.database_url) as session:
        result = import_map_export(session, export).model_dump()
        result["evidence_created"] = attach_sketchup_evidence(session, export)
    print(json.dumps({**summary, "import": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
