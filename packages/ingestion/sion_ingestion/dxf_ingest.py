"""Minimal DXF semantic ingest. No ezdxf dependency.

Extracts TEXT/MTEXT, INSERT, LINE, and closed LWPOLYLINE as unverified claims.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from sion_ingestion.document_ingest import attach_document_evidence
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export


def _entities(text: str) -> list[tuple[str, dict[str, str]]]:
    """Tokenise ASCII DXF group-code pairs into (entity type, {code: value})."""
    lines = text.splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    entities: list[tuple[str, dict[str, str]]] = []
    current: tuple[str, dict[str, str]] | None = None
    for code, value in pairs:
        if code == "0":
            if current is not None:
                entities.append(current)
            current = None if value in {"SECTION", "ENDSEC", "EOF"} else (value, {})
        elif current is not None:
            current[1].setdefault(code, value)
    if current is not None:
        entities.append(current)
    return entities


def _parse_with_ezdxf(path: Path) -> list[dict] | None:
    """Parse with ezdxf (MIT) when installed; return None to use the fallback."""
    try:
        import ezdxf
        from ezdxf import recover
    except ImportError:
        return None
    try:
        doc, auditor = recover.readfile(str(path))
    except (IOError, ezdxf.DXFStructureError):
        return None
    if auditor.has_errors or auditor.has_fixes:
        # Recovery dropped or fixed entities (e.g. INSERTs of undefined blocks); the
        # tolerant fallback keeps every annotated item instead.
        return None
    items: list[dict] = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        layer = str(entity.dxf.get("layer", ""))
        if kind == "TEXT" and entity.dxf.get("text"):
            items.append({"kind": "annotation", "name": entity.dxf.text, "layer": layer})
        elif kind == "MTEXT":
            text = entity.plain_text().strip()
            if text:
                items.append({"kind": "annotation", "name": text, "layer": layer})
        elif kind == "INSERT":
            items.append({"kind": "block", "name": entity.dxf.name, "layer": layer})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{layer or '0'}", "layer": layer})
        elif kind == "LWPOLYLINE":
            closed = bool(entity.closed)
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{layer or '0'}",
                "layer": layer,
            })
    return items


def parse_dxf(path: Path, *, use_ezdxf: bool = True) -> list[dict]:
    """Extract annotations, blocks, segments and closed spaces from a DXF file.

    Uses ezdxf when available (handles binary/legacy DXF and recovery); falls back
    to a minimal ASCII group-code parser otherwise.
    """
    if use_ezdxf:
        parsed = _parse_with_ezdxf(path)
        if parsed:
            return parsed
    return _parse_fallback(path)


def _parse_fallback(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    items: list[dict] = []
    for kind, values in _entities(text):
        if kind in {"TEXT", "MTEXT"} and values.get("1"):
            items.append({"kind": "annotation", "name": values["1"], "layer": values.get("8", "")})
        elif kind == "INSERT" and values.get("2"):
            items.append({"kind": "block", "name": values["2"], "layer": values.get("8", "")})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{values.get('8', '0')}", "layer": values.get("8", "")})
        elif kind == "LWPOLYLINE":
            closed = bool(int(values.get("70", "0") or 0) & 1)
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{values.get('8', '0')}",
                "layer": values.get("8", ""),
            })
    return items


def build_dxf_export(path: Path) -> MapExport:
    items = parse_dxf(path)
    drawing_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    nodes = [
        MapNode(
            stable_key=drawing_key,
            entity_type_id="Artifact",
            name=path.name,
            category="cad_bim",
            external_uri=f"file:///{path.resolve().as_posix()}",
            properties={"format": "dxf", "item_count": len(items)},
        )
    ]
    edges: list[MapEdge] = []
    for index, item in enumerate(items):
        entity_type = "Concept" if item["kind"] in {"annotation", "space"} else "Deliverable"
        key = f"concept:{drawing_key}:{index}"
        nodes.append(
            MapNode(
                stable_key=key,
                entity_type_id=entity_type,
                name=str(item["name"])[:500],
                category="cad_bim",
                properties=item,
            )
        )
        edges.append(
            MapEdge(
                stable_key=f"{key}:EXTRACTED_FROM:{drawing_key}",
                source_stable_key=key,
                target_stable_key=drawing_key,
                relation_type_id="EXTRACTED_FROM",
                confidence=0.5,
                verification_state="unverified",
                source_kind="file",
                properties={"locator": f"dxf:{index}", "kind": item["kind"]},
            )
        )
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "dxf-ingest",
            "expected_node_count": len(nodes),
            "expected_edge_count": len(edges),
            "nodes": [node.model_dump() for node in nodes],
            "edges": [edge.model_dump() for edge in edges],
        }
    )


def ingest_dxf(session: Session, path: Path) -> dict:
    export = build_dxf_export(path)
    result = import_map_export(session, export)
    evidence = attach_document_evidence(session, export)
    return {
        "file": str(path),
        "created_nodes": result.created_nodes,
        "created_edges": result.created_edges,
        "evidence_created": evidence,
        "verification_state": "unverified",
    }
