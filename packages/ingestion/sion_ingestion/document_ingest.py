"""Local document ingestion into the canonical map-export contract.

Claims stay unverified. No external model is called.

Formats: ``.md``/``.txt``/``.csv`` (always), ``.docx`` (python-docx from the
``documents`` extra, else a built-in reader of the OOXML ``word/document.xml``),
``.pdf`` (pypdf from the ``documents`` extra; without it PDFs are reported as
skipped, never guessed). DOCX "Heading 1-3" paragraphs become markdown headings
so claim extraction is uniform across formats.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from sion_api import models
from sion_core import MissingExtra, require
from sion_core.optional import is_available
from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export

_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_HEADING_STYLE = re.compile(r"^heading\s*([1-3])$", re.IGNORECASE)

TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv"})
DOCUMENT_SUFFIXES = TEXT_SUFFIXES | {".docx", ".pdf"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentUnreadable(ValueError):
    """The file has a supported suffix but its content cannot be read."""


@dataclass(frozen=True)
class ExtractedText:
    text: str
    extractor: str
    page_count: int | None = None


def _key(prefix: str, raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def supported_suffixes() -> set[str]:
    """Suffixes ingestible with the libraries installed right now."""
    suffixes = set(TEXT_SUFFIXES) | {".docx"}  # DOCX always has the built-in reader
    if is_available("pypdf"):
        suffixes.add(".pdf")
    return suffixes


def _heading_line(text: str, style_name: str) -> str:
    match = _HEADING_STYLE.match(style_name.strip())
    return f"{'#' * int(match.group(1))} {text}" if match else text


def _docx_with_python_docx(path: Path) -> str:
    docx = require("docx", extra="documents")
    lines: list[str] = []
    for para in docx.Document(str(path)).paragraphs:
        text = para.text.strip()
        if text:
            lines.append(_heading_line(text, (para.style.name if para.style is not None else "") or ""))
    return "\n".join(lines)


def _docx_builtin(path: Path) -> str:
    """Body-level paragraphs of word/document.xml; heading levels from styles.xml names."""
    with zipfile.ZipFile(path) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        style_names: dict[str, str] = {}
        if "word/styles.xml" in archive.namelist():
            for style in ElementTree.fromstring(archive.read("word/styles.xml")).iter(f"{_W}style"):
                name = style.find(f"{_W}name")
                if name is not None:
                    style_names[style.get(f"{_W}styleId", "")] = name.get(f"{_W}val", "")
    body = document.find(f"{_W}body")
    lines: list[str] = []
    for para in body.findall(f"{_W}p") if body is not None else []:
        parts: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in {f"{_W}br", f"{_W}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if not text:
            continue
        style = para.find(f"{_W}pPr/{_W}pStyle")
        style_id = style.get(f"{_W}val", "") if style is not None else ""
        lines.append(_heading_line(text, style_names.get(style_id, style_id)))
    return "\n".join(lines)


def extract_text(path: Path) -> ExtractedText:
    """Text of one document. Raises :class:`MissingExtra` (PDF without pypdf) or :class:`DocumentUnreadable`."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pypdf = require("pypdf", extra="documents")
        try:
            reader = pypdf.PdfReader(str(path))
            if reader.is_encrypted:
                raise DocumentUnreadable("encrypted PDF")
            pages = [page.extract_text() or "" for page in reader.pages]
        except DocumentUnreadable:
            raise
        except Exception as exc:  # pypdf raises several error types for damaged files
            raise DocumentUnreadable(f"PDF could not be read ({type(exc).__name__}: {exc})") from exc
        return ExtractedText("\n".join(pages), "pypdf", len(pages))
    if suffix == ".docx":
        try:
            if is_available("docx"):
                return ExtractedText(_docx_with_python_docx(path), "python-docx")
            return ExtractedText(_docx_builtin(path), "docx-builtin")
        except Exception as exc:  # BadZipFile, KeyError, ParseError, python-docx package errors
            raise DocumentUnreadable(f"DOCX could not be read ({type(exc).__name__}: {exc})") from exc
    if suffix in TEXT_SUFFIXES:
        return ExtractedText(path.read_text(encoding="utf-8", errors="replace"), "text")
    raise DocumentUnreadable(f"unsupported document type: {suffix or '(none)'}")


def build_document_export(
    paths: list[Path],
    source: str = "document-ingest",
    *,
    extracted: dict[Path, ExtractedText] | None = None,
) -> MapExport:
    nodes: list[MapNode] = []
    edges: list[MapEdge] = []
    for path in paths:
        content = (extracted or {}).get(path) or extract_text(path)
        text = content.text
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
                    "extractor": content.extractor,
                    **({"page_count": content.page_count} if content.page_count is not None else {}),
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
    """Ingest documents; unreadable or unsupported files are reported in ``skipped`` (never a 500)."""
    files: list[Path] = []
    extracted: dict[Path, ExtractedText] = {}
    skipped: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file():
            skipped.append({"path": str(path), "reason": "not a file"})
            continue
        if path.suffix.lower() not in DOCUMENT_SUFFIXES:
            skipped.append({"path": str(path), "reason": f"unsupported type {path.suffix.lower() or '(none)'}"})
            continue
        try:
            content = extract_text(path)
        except (MissingExtra, DocumentUnreadable) as exc:
            skipped.append({"path": str(path), "reason": str(exc)})
            continue
        if not content.text.strip():
            skipped.append({"path": str(path), "reason": "no extractable text (scanned PDF? OCR is not performed)"})
            continue
        files.append(path)
        extracted[path] = content
    export = build_document_export(files, extracted=extracted)
    result = import_map_export(session, export)
    evidence = attach_document_evidence(session, export)
    return {
        "files": [str(path) for path in files],
        "extractors": {str(path): extracted[path].extractor for path in files},
        "skipped": skipped,
        "created_nodes": result.created_nodes,
        "created_edges": result.created_edges,
        "skipped_nodes": result.skipped_nodes,
        "skipped_edges": result.skipped_edges,
        "evidence_created": evidence,
        "verification_state": "unverified",
    }
