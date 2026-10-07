"""DXF semantic ingest into the Sion graph as unverified claims.

Reading goes through :mod:`sion_cad.reader` (ezdxf with recover/CP949 handling,
built-in text fallback). Extracts TEXT/MTEXT, INSERT, LINE and LWPOLYLINE.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sion_ingestion.document_ingest import attach_document_evidence
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export
from sqlalchemy.orm import Session

from . import reader


def ezdxf_available() -> bool:
    return reader.ezdxf_available()


def parse_dxf_with_parser(path: Path, *, prefer_ezdxf: bool = True) -> tuple[list[dict], str]:
    """Return (items, parser): 'ezdxf' when the optional extra is installed, else 'text-fallback'."""
    result = reader.read_entities(path, prefer_ezdxf=prefer_ezdxf)
    return result.items, result.parser


def parse_dxf(path: Path, *, prefer_ezdxf: bool = False) -> list[dict]:
    return parse_dxf_with_parser(path, prefer_ezdxf=prefer_ezdxf)[0]


def _parse_text(path: Path) -> list[dict]:
    return reader.parse_text_items(path)


def build_dxf_export(path: Path) -> MapExport:
    result = reader.read_entities(path)
    items, parser = result.items, result.parser
    drawing_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    nodes = [
        MapNode(
            stable_key=drawing_key,
            entity_type_id="Artifact",
            name=path.name,
            category="cad_bim",
            external_uri=f"file:///{path.resolve().as_posix()}",
            properties={"format": "dxf", "parser": parser, "item_count": len(items), "warnings": result.warnings[:20]},
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
