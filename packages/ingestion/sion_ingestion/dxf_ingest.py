"""DXF semantic ingest.

Uses ``ezdxf`` when installed (binary DXF, encodings, MTEXT formatting) and
falls back to a dependency-free ASCII group-code scanner otherwise.
Extracts TEXT/MTEXT, INSERT, LINE, and LWPOLYLINE as unverified claims.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from sion_ingestion.document_ingest import attach_document_evidence
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export


def _pairs(text: str) -> list[tuple[str, str]]:
    """Return DXF (group code, value) pairs. Codes and values alternate by line."""
    # split on newline only: str.splitlines() also breaks on \x1c-\x1e, \x85, ...
    lines = text.replace("\r\n", "\n").split("\n")
    pairs: list[tuple[str, str]] = []
    index = 0
    while index + 1 < len(lines):
        pairs.append((lines[index].strip(), lines[index + 1].strip()))
        index += 2
    return pairs


def _sections(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Group pairs into entities keyed by group code 0.

    Splitting on group codes (not raw text) keeps values such as layer ``0``
    from being mistaken for entity boundaries.
    """
    entities: list[tuple[str, list[tuple[str, str]]]] = []
    current: tuple[str, list[tuple[str, str]]] | None = None
    for code, value in _pairs(text):
        if code == "0":
            if current is not None:
                entities.append(current)
            current = None if value in {"SECTION", "ENDSEC", "EOF"} else (value, [])
        elif current is not None:
            current[1].append((code, value))
    if current is not None:
        entities.append(current)
    return entities


def _parse_fallback(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    items: list[dict] = []
    for kind, pairs in _sections(text):
        values: dict[str, str] = {}
        for code, value in pairs:
            values.setdefault(code, value)
        if kind in {"TEXT", "MTEXT"} and values.get("1"):
            items.append({"kind": "annotation", "name": values["1"], "layer": values.get("8", "")})
        elif kind == "INSERT" and values.get("2"):
            items.append({"kind": "block", "name": values["2"], "layer": values.get("8", "")})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{values.get('8', '0')}", "layer": values.get("8", "")})
        elif kind == "LWPOLYLINE":
            try:
                closed = bool(int(values.get("70", "0")) & 1)
            except ValueError:
                closed = False
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{values.get('8', '0')}",
                "layer": values.get("8", ""),
            })
    return items


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
        elif kind == "MTEXT":
            text = entity.plain_text()
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


def parse_dxf_with_parser(path: Path, *, prefer_ezdxf: bool = True) -> tuple[list[dict], str]:
    """Return (items, parser) where parser is 'ezdxf' or 'ascii-fallback'."""
    if prefer_ezdxf and ezdxf_available():
        try:
            return _parse_with_ezdxf(path), "ezdxf"
        except Exception:
            pass  # unreadable for ezdxf; use the tolerant scanner
    return _parse_fallback(path), "ascii-fallback"


def parse_dxf(path: Path, *, prefer_ezdxf: bool = True) -> list[dict]:
    return parse_dxf_with_parser(path, prefer_ezdxf=prefer_ezdxf)[0]


def build_dxf_export(path: Path, *, prefer_ezdxf: bool = True) -> MapExport:
    items, parser = parse_dxf_with_parser(path, prefer_ezdxf=prefer_ezdxf)
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
