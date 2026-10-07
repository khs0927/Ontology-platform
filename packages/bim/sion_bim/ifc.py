"""IFC ingestion with optional IfcOpenShell.

When ``ifcopenshell`` is importable it is used to enumerate IfcProduct /
IfcSpatialElement instances. Otherwise a dependency-free STEP (ISO-10303-21)
line scanner extracts the same subset (GlobalId + Name) from the DATA section.
All produced claims are ``unverified``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sion_ingestion.document_ingest import attach_document_evidence
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export
from sqlalchemy.orm import Session

# Element classes surfaced as graph nodes by the fallback scanner.
SPATIAL = {"IFCPROJECT", "IFCSITE", "IFCBUILDING", "IFCBUILDINGSTOREY", "IFCSPACE"}
ELEMENTS = {
    "IFCWALL", "IFCWALLSTANDARDCASE", "IFCSLAB", "IFCDOOR", "IFCWINDOW", "IFCCOLUMN",
    "IFCBEAM", "IFCSTAIR", "IFCROOF", "IFCRAILING", "IFCCOVERING", "IFCPLATE",
    "IFCMEMBER", "IFCFURNISHINGELEMENT", "IFCFLOWTERMINAL", "IFCFLOWSEGMENT",
    "IFCFLOWFITTING", "IFCDISTRIBUTIONELEMENT", "IFCBUILDINGELEMENTPROXY",
}
_LINE = re.compile(r"^#(\d+)\s*=\s*(IFC[A-Z0-9_]+)\s*\((.*)\)\s*;\s*$", re.DOTALL)


def _split_args(raw: str) -> list[str]:
    args: list[str] = []
    depth = 0
    in_str = False
    buf: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    buf.append("'")
                    i += 1
                else:
                    in_str = False
        elif ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    args.append("".join(buf).strip())
    return args


def _string(value: str) -> str | None:
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return None


def ifcopenshell_available() -> bool:
    try:
        import ifcopenshell  # noqa: F401
    except Exception:
        return False
    return True


def _parse_with_ifcopenshell(path: Path) -> list[dict]:
    import ifcopenshell

    model = ifcopenshell.open(str(path))
    items: list[dict] = []
    seen: set[int] = set()
    for cls in ("IfcSpatialElement", "IfcProduct", "IfcProject"):
        try:
            instances = model.by_type(cls)
        except Exception:
            continue
        for inst in instances:
            if inst.id() in seen:
                continue
            seen.add(inst.id())
            ifc_class = inst.is_a()
            items.append({
                "ifc_class": ifc_class,
                "global_id": getattr(inst, "GlobalId", None),
                "name": getattr(inst, "Name", None) or ifc_class,
                "spatial": ifc_class.upper() in SPATIAL,
            })
    return items


def _parse_fallback(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("DATA;")
    body = text[start + 5:] if start >= 0 else text
    items: list[dict] = []
    for statement in body.split(";\n"):
        statement = statement.strip()
        if not statement or statement.startswith("ENDSEC"):
            continue
        match = _LINE.match(statement + ";")
        if not match:
            continue
        ifc_class = match.group(2)
        if ifc_class not in SPATIAL and ifc_class not in ELEMENTS:
            continue
        args = _split_args(match.group(3))
        global_id = _string(args[0]) if args else None
        name = _string(args[2]) if len(args) > 2 else None
        items.append({
            "ifc_class": ifc_class,
            "global_id": global_id,
            "name": name or ifc_class,
            "spatial": ifc_class in SPATIAL,
        })
    return items


def parse_ifc(path: Path, *, prefer_ifcopenshell: bool = True) -> tuple[list[dict], str]:
    """Return (items, parser) where parser is 'ifcopenshell' or 'step-fallback'."""
    if prefer_ifcopenshell and ifcopenshell_available():
        try:
            return _parse_with_ifcopenshell(path), "ifcopenshell"
        except Exception:
            pass  # fall through to the text scanner
    return _parse_fallback(path), "step-fallback"


def build_ifc_export(path: Path, *, prefer_ifcopenshell: bool = True) -> tuple[MapExport, str]:
    items, parser = parse_ifc(path, prefer_ifcopenshell=prefer_ifcopenshell)
    model_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    nodes = [
        MapNode(
            stable_key=model_key,
            entity_type_id="Artifact",
            name=path.name,
            category="cad_bim",
            external_uri=f"file:///{path.resolve().as_posix()}",
            properties={"format": "ifc", "parser": parser, "item_count": len(items)},
        )
    ]
    edges: list[MapEdge] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ident = item.get("global_id") or f"idx{index}"
        key = f"ifc:{model_key}:{ident}"
        if key in seen:
            continue
        seen.add(key)
        nodes.append(
            MapNode(
                stable_key=key,
                entity_type_id="Concept" if item["spatial"] else "SystemComponent",
                name=str(item["name"])[:500],
                category="cad_bim",
                properties={**item, "verification_state": "unverified"},
            )
        )
        edges.append(
            MapEdge(
                stable_key=f"{key}:EXTRACTED_FROM:{model_key}",
                source_stable_key=key,
                target_stable_key=model_key,
                relation_type_id="EXTRACTED_FROM",
                confidence=0.6,
                verification_state="unverified",
                source_kind="file",
                properties={"locator": f"ifc:{ident}", "ifc_class": item["ifc_class"]},
            )
        )
    export = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "ifc-ingest",
            "expected_node_count": len(nodes),
            "expected_edge_count": len(edges),
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in edges],
        }
    )
    return export, parser


def ingest_ifc(session: Session, path: Path) -> dict:
    export, parser = build_ifc_export(path)
    result = import_map_export(session, export)
    evidence = attach_document_evidence(session, export)
    return {
        "file": str(path),
        "parser": parser,
        "created_nodes": result.created_nodes,
        "created_edges": result.created_edges,
        "evidence_created": evidence,
        "verification_state": "unverified",
    }
