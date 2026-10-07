"""Minimal DXF semantic ingest. No ezdxf dependency.

Extracts TEXT/MTEXT, INSERT, LINE, and closed LWPOLYLINE as unverified claims.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from sion_ingestion.document_ingest import attach_document_evidence
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export


def _pairs(body: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in body.splitlines()]
    pairs: list[tuple[str, str]] = []
    index = 0
    while index + 1 < len(lines):
        pairs.append((lines[index], lines[index + 1]))
        index += 2
    return pairs


def _sections(text: str) -> list[tuple[str, str]]:
    """Group (code, value) pairs into entities, split on group code 0.

    Group codes are whitespace-padded in many writers (e.g. "  0"), so codes
    are compared after stripping. Only the ENTITIES section is scanned when
    present, so BLOCKS definitions are not double-counted.
    """
    lines = text.splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    in_entities = not any(code == "2" and value == "ENTITIES" for code, value in pairs)
    sections: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    previous_section = False
    for code, value in pairs:
        if code == "0":
            if current is not None and in_entities:
                sections.append((current, "\n".join(body)))
            current, body = None, []
            if value == "SECTION":
                previous_section = True
                continue
            if value == "ENDSEC":
                in_entities = in_entities and not any(c == "2" and v == "ENTITIES" for c, v in pairs)
                continue
            if value not in {"EOF"}:
                current = value
            previous_section = False
            continue
        if previous_section and code == "2":
            in_entities = value == "ENTITIES"
            previous_section = False
            continue
        if current is not None:
            body.extend([code, value])
    if current is not None and in_entities:
        sections.append((current, "\n".join(body)))
    return sections


def ezdxf_available() -> bool:
    try:
        import ezdxf  # noqa: F401
    except Exception:
        return False
    return True


def _parse_with_ezdxf(path: Path) -> list[dict]:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    items: list[dict] = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        layer = entity.dxf.get("layer", "")
        if kind == "TEXT" and entity.dxf.get("text"):
            items.append({"kind": "annotation", "name": entity.dxf.text, "layer": layer})
        elif kind == "MTEXT" and entity.text:
            items.append({"kind": "annotation", "name": entity.plain_text(), "layer": layer})
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


def parse_dxf_with_parser(path: Path, *, prefer_ezdxf: bool = True) -> tuple[list[dict], str]:
    """Return (items, parser): 'ezdxf' when the optional extra is installed, else 'text-fallback'."""
    if prefer_ezdxf and ezdxf_available():
        try:
            return _parse_with_ezdxf(path), "ezdxf"
        except Exception:
            pass
    return _parse_text(path), "text-fallback"


def parse_dxf(path: Path, *, prefer_ezdxf: bool = False) -> list[dict]:
    return parse_dxf_with_parser(path, prefer_ezdxf=prefer_ezdxf)[0]


def _parse_text(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    items: list[dict] = []
    for kind, body in _sections(text):
        pairs = _pairs(body)
        values = {code: value for code, value in pairs}
        if kind in {"TEXT", "MTEXT"} and values.get("1"):
            items.append({"kind": "annotation", "name": values["1"], "layer": values.get("8", "")})
        elif kind == "INSERT" and values.get("2"):
            items.append({"kind": "block", "name": values["2"], "layer": values.get("8", "")})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{values.get('8', '0')}", "layer": values.get("8", "")})
        elif kind == "LWPOLYLINE":
            closed = values.get("70") == "1"
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{values.get('8', '0')}",
                "layer": values.get("8", ""),
            })
    return items


def build_dxf_export(path: Path) -> MapExport:
    items, parser = parse_dxf_with_parser(path)
    drawing_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    nodes = [
        MapNode(
            stable_key=drawing_key,
            entity_type_id="Artifact",
            name=path.name,
            category="cad_bim",
            external_uri=f"file:///{path.resolve().as_posix()}",
            properties={"format": "dxf", "parser": parser, "item_count": len(items)},
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
