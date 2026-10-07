"""Local document ingestion into the canonical map-export contract.

Claims stay unverified. No external model is called.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_api import models
from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export


_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _key(prefix: str, raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


TEXT_SUFFIXES = {".md", ".txt", ".csv"}


def supported_suffixes() -> set[str]:
    """Suffixes ingestible with the currently installed optional libraries."""
    suffixes = set(TEXT_SUFFIXES)
    try:
        import pypdf  # noqa: F401
        suffixes.add(".pdf")
    except ImportError:
        pass
    try:
        import docx  # noqa: F401
        suffixes.add(".docx")
    except ImportError:
        pass
    return suffixes


def extract_text(path: Path) -> str:
    """Return document text; PDF via pypdf (BSD-3), DOCX via python-docx (MIT).

    DOCX headings are converted to markdown ``#`` headings so claim extraction
    stays uniform across formats.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        import docx

        lines: list[str] = []
        for para in docx.Document(str(path)).paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            match = re.match(r"Heading\s*([1-3])", style)
            lines.append(f"{'#' * int(match.group(1))} {text}" if match else text)
        return "\n".join(lines)
    return path.read_text(encoding="utf-8", errors="replace")


def build_document_export(paths: list[Path], source: str = "document-ingest") -> MapExport:
    nodes: list[MapNode] = []
    edges: list[MapEdge] = []
    for path in paths:
        text = extract_text(path)
        doc_key = _key("document", f"{path.resolve()}:{path.stat().st_size}")
        title = path.stem
        headings = [match.group(2).strip() for match in _HEADING.finditer(text)]
        if headings:
            title = headings[0]
        nodes.append(
            MapNode(
                stable_key=doc_key,
                entity_type_id="Document",
                name=title[:500],
                category="content_assets",
                description=text[:500] or None,
                external_uri=f"file:///{path.resolve().as_posix()}",
                properties={
                    "path": str(path),
                    "byte_size": path.stat().st_size,
                    "heading_count": len(headings),
                    "excerpt_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            )
        )
        claims = headings or [line.strip() for line in text.splitlines() if line.strip()][:8]
        for index, claim in enumerate(claims[:40]):
            concept_key = _key("concept", f"{doc_key}:{index}:{claim}")
            nodes.append(
                MapNode(
                    stable_key=concept_key,
                    entity_type_id="Concept",
                    name=claim[:500],
                    category="data_validation",
                    properties={"ordinal": index, "verification_state": "unverified"},
                )
            )
            edges.append(
                MapEdge(
                    stable_key=f"{concept_key}:EXTRACTED_FROM:{doc_key}",
                    source_stable_key=concept_key,
                    target_stable_key=doc_key,
                    relation_type_id="EXTRACTED_FROM",
                    confidence=0.4,
                    verification_state="unverified",
                    source_kind="document",
                    properties={"locator": f"heading-or-line:{index}"},
                )
            )
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": source,
            "expected_node_count": len(nodes),
            "expected_edge_count": len(edges),
            "nodes": [node.model_dump() for node in nodes],
            "edges": [edge.model_dump() for edge in edges],
        }
    )


def attach_document_evidence(session: Session, export: MapExport) -> int:
    created = 0
    for edge in export.edges:
        relation = session.scalar(
            select(models.Relation).where(models.Relation.stable_key == edge.stable_key)
        )
        if relation is None:
            continue
        existing = session.scalar(
            select(models.Evidence).where(
                models.Evidence.relation_id == relation.id,
                models.Evidence.source_locator == edge.properties.get("locator"),
            )
        )
        if existing is not None:
            continue
        target = session.get(models.Entity, relation.target_entity_id)
        session.add(
            models.Evidence(
                relation_id=relation.id,
                source_uri=(target.external_uri if target and target.external_uri else "urn:sion:document"),
                source_locator=str(edge.properties.get("locator") or ""),
                excerpt_hash=None,
                confidence=edge.confidence,
                verification_state="unverified",
                extractor="local-heading-line",
                properties={"source": export.source},
            )
        )
        created += 1
    session.commit()
    return created


def ingest_documents(session: Session, paths: list[Path]) -> dict:
    files = [path for path in paths if path.is_file() and path.suffix.lower() in supported_suffixes()]
    export = build_document_export(files)
    result = import_map_export(session, export)
    evidence = attach_document_evidence(session, export)
    return {
        "files": [str(path) for path in files],
        "created_nodes": result.created_nodes,
        "created_edges": result.created_edges,
        "skipped_nodes": result.skipped_nodes,
        "skipped_edges": result.skipped_edges,
        "evidence_created": evidence,
        "verification_state": "unverified",
    }
