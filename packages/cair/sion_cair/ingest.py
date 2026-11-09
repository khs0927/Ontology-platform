"""Thin ingestion adapter: khs0927/Ontology (``aec_intelligence``) DXF/IFC → Sion graph + evidence.

Consolidation phase 1 (docs/CONSOLIDATION_PLAN.md). Ontology's ingestion stays the producer of
CAIR snapshots (contract ``aec-cair-snapshot/1``); this module only

1. runs Ontology's own CLI (``aec_intelligence.cli ingest-dxf`` / ``ingest-file``) in a **separate
   process** against a throw-away repository root and reads ``03_CAIR/project-cair.json`` back, and
2. maps that snapshot onto Sion's ``sion-map-export/v1`` graph model and attaches one evidence row per
   ``EXTRACTED_FROM`` relation.

The process boundary is deliberate: the same code path works with the bundled subtree
(``packages/aec``), with an external checkout (``ontology_root=C:\\CODE\\Ontology`` → its ``src`` is
put on ``PYTHONPATH``) and with a pinned install in another virtualenv (``python=...``), without two
copies of the ``aec_intelligence`` import package ever meeting in one interpreter.

Rules kept from docs/INTEGRATION_CONTRACTS.md: everything lands ``unverified`` (advisory, never
canonical), import is idempotent and non-destructive (``import_map_export``), and a snapshot that does
not satisfy the contract is refused instead of being guessed at.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sion_ingestion.map_import import MapEdge, MapExport, MapNode, import_map_export
from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapter import AecCairError, bundled_root

CONTRACT = "aec-cair-snapshot/1"
SOURCE = "aec-cair-ingest"
_CAIR_VERSION = re.compile(r"^0\.[0-9]+\.[0-9]+$")  # CAIR_SCHEMA_VERSION 0.x = contract /1
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DXF_SUFFIXES = {".dxf"}
_FILE_SUFFIXES = {".ifc"}
#: CAIR predicate -> Sion relation type (seeded in migrations/004). Anything else -> RELATED_TO.
PREDICATE_MAP = {
    "containedIn": "PART_OF",
    "partOf": "PART_OF",
    "hostedBy": "PART_OF",
    "derivedFrom": "DERIVED_FROM",
    "references": "REFERENCES",
    "connectsTo": "CONNECTS_TO",
    "adjacentTo": "CONNECTS_TO",
}
#: CAIR predicates whose direction is parent -> child; imported as child PART_OF parent.
REVERSED_PREDICATES = {"contains": "PART_OF"}
#: Project-level membership is already expressed by EXTRACTED_FROM to the source artifact.
SKIPPED_PREDICATES = frozenset({"containsElement"})


def _ontology_command(
    source: Path, project_id: str, work_root: Path, *, ontology_root: str | Path | None, python: str | None
) -> tuple[list[str], dict[str, str], Path]:
    if source.suffix.lower() in _DXF_SUFFIXES:
        sub = ["ingest-dxf", str(source), "--project-id", project_id]
    elif source.suffix.lower() in _FILE_SUFFIXES:
        sub = ["ingest-file", str(source), "--project-id", project_id]
    else:
        raise AecCairError(f"unsupported source for the Ontology adapter: {source.suffix or source.name} (DXF/IFC only)")
    env = dict(os.environ)
    root = str(ontology_root or "bundled")
    if root.strip().lower() == "bundled":
        cwd = bundled_root()
    else:
        cwd = Path(root).expanduser().resolve()
        src = cwd / "src"
        if not (src / "aec_intelligence" / "__init__.py").is_file():
            raise AecCairError(f"not an Ontology checkout (no src/aec_intelligence): {cwd}")
        env["PYTHONPATH"] = os.pathsep.join([str(src), *filter(None, [env.get("PYTHONPATH")])])
    command = [python or sys.executable, "-m", "aec_intelligence.cli", "--root", str(work_root), *sub]
    return command, env, cwd


def run_ontology_ingest(
    source: str | Path,
    project_id: str,
    *,
    ontology_root: str | Path | None = None,
    python: str | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run Ontology's DXF/IFC ingestion in a subprocess and return the CAIR snapshot dict.

    ``ontology_root``: ``None``/``"bundled"`` (packages/aec) or a path to a khs0927/Ontology checkout.
    ``python``: interpreter that has ``aec_intelligence`` importable (e.g. a venv with a pinned
    ``pip install "aec-intelligence[cad,bim] @ git+https://github.com/khs0927/Ontology@<sha>"``).
    """
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise AecCairError(f"source file not found: {path}")
    if not _PROJECT_ID.fullmatch(project_id):
        raise AecCairError("project_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
    with tempfile.TemporaryDirectory(prefix="sion-aec-ingest-") as tmp:
        work_root = Path(tmp)
        command, env, cwd = _ontology_command(path, project_id, work_root, ontology_root=ontology_root, python=python)
        try:
            proc = subprocess.run(
                command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AecCairError(f"Ontology ingestion timed out after {timeout_seconds:g}s") from exc
        cair_path = work_root / "projects" / project_id / "03_CAIR" / "project-cair.json"
        if proc.returncode not in (0, 2) or not cair_path.is_file():
            detail = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise AecCairError(f"Ontology ingestion failed (exit {proc.returncode}): {detail}")
        snapshot = json.loads(cair_path.read_text(encoding="utf-8"))
    problems = snapshot_errors(snapshot)
    if problems:
        raise AecCairError("CAIR snapshot violates " + CONTRACT + ": " + "; ".join(problems[:5]))
    return snapshot


def snapshot_errors(snapshot: Any) -> list[str]:
    """Structural checks of ``aec-cair-snapshot/1`` that need no ``jsonschema`` (fail closed)."""
    if not isinstance(snapshot, dict):
        return ["snapshot is not an object"]
    errors: list[str] = []
    version = snapshot.get("schema_version")
    if not isinstance(version, str) or not _CAIR_VERSION.fullmatch(version):
        errors.append(f"schema_version must be a CAIR 0.x version, got {version!r}")
    for key in ("project_id", "snapshot_id", "status"):
        if not isinstance(snapshot.get(key), str) or not snapshot.get(key):
            errors.append(f"{key} missing")
    if snapshot.get("status") == "FAILED":
        errors.append("status is FAILED: nothing trustworthy to import")
    objects, relations = snapshot.get("objects"), snapshot.get("relations")
    if not isinstance(objects, list):
        errors.append("objects must be a list")
        objects = []
    if not isinstance(relations, list):
        errors.append("relations must be a list")
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not isinstance(obj.get("type"), str):
            errors.append(f"objects[{index}] needs string id and type")
            continue
        if not isinstance(obj.get("source"), dict):
            errors.append(f"objects[{index}].source missing")
    return errors


def _artifact_key(snapshot: dict[str, Any], source: dict[str, Any], provenance: dict[str, Any]) -> str:
    digest = provenance.get("source_hash") or source.get("artifact_id") or source.get("file") or snapshot["project_id"]
    return "aec-artifact:" + hashlib.sha256(str(digest).encode("utf-8")).hexdigest()[:24]


def _object_name(obj: dict[str, Any]) -> str:
    props = obj.get("properties") or {}
    classification = obj.get("classification") or {}
    for value in (props.get("name"), props.get("text"), props.get("label"), classification.get("label"), obj["type"]):
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return obj["type"][:500]


def cair_snapshot_to_map_export(snapshot: dict[str, Any]) -> MapExport:
    """Map an ``aec-cair-snapshot/1`` dict onto ``sion-map-export/v1`` (pure, deterministic).

    * one ``Artifact`` node per distinct source file (keyed by the source hash);
    * one ``Concept`` node per CAIR object (stable key = CAIR id, which is a uuid5 of the source id);
    * ``EXTRACTED_FROM`` object → artifact, confidence = classification confidence, ``unverified``;
    * object↔object CAIR relations mapped through :data:`PREDICATE_MAP` (default ``RELATED_TO``;
      :data:`REVERSED_PREDICATES` such as IFC ``contains`` become child ``PART_OF`` parent),
      original predicate kept in ``properties.cair_predicate``. Relations to ids outside the snapshot
      and :data:`SKIPPED_PREDICATES` are not imported.
    """
    problems = snapshot_errors(snapshot)
    if problems:
        raise AecCairError("CAIR snapshot violates " + CONTRACT + ": " + "; ".join(problems[:5]))
    nodes: dict[str, MapNode] = {}
    edges: list[MapEdge] = []
    object_keys: dict[str, str] = {}
    for obj in snapshot["objects"]:
        source = obj.get("source") or {}
        provenance = obj.get("provenance") or {}
        classification = obj.get("classification") or {}
        artifact_key = _artifact_key(snapshot, source, provenance)
        if artifact_key not in nodes:
            file_name = Path(str(source.get("file") or "source")).name or "source"
            nodes[artifact_key] = MapNode(
                stable_key=artifact_key,
                entity_type_id="Artifact",
                name=file_name[:500],
                category="cad_bim",
                external_uri="urn:sha256:" + provenance["source_hash"] if provenance.get("source_hash") else None,
                properties={
                    "format": str(source.get("format") or provenance.get("source_format") or "").lower(),
                    "parser": provenance.get("parser"),
                    "parser_version": provenance.get("parser_version"),
                    "aec_artifact_id": source.get("artifact_id"),
                    "cair_snapshot_id": snapshot["snapshot_id"],
                    "cair_schema_version": snapshot["schema_version"],
                    "aec_project_id": snapshot["project_id"],
                },
            )
        key = "cair:" + obj["id"]
        object_keys[obj["id"]] = key
        nodes[key] = MapNode(
            stable_key=key,
            entity_type_id="Concept",
            name=_object_name(obj),
            category="cad_bim",
            external_uri=obj["id"],
            properties={
                "cair_type": obj["type"],
                "classification": classification or None,
                "source": source,
                "geometry_ref": obj.get("geometry_ref"),
                "bbox": obj.get("bbox") or {},
                "properties": obj.get("properties") or {},
            },
        )
        confidence = classification.get("confidence")
        edges.append(
            MapEdge(
                stable_key=f"{key}:EXTRACTED_FROM:{artifact_key}",
                source_stable_key=key,
                target_stable_key=artifact_key,
                relation_type_id="EXTRACTED_FROM",
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                verification_state="unverified",
                source_kind="file",
                properties={
                    "locator": obj.get("geometry_ref") or f"{source.get('format', 'cair')}:{source.get('entity_id')}",
                    "cair_type": obj["type"],
                    "classification_state": classification.get("state"),
                    "extractor": f"aec-cair/{provenance.get('parser') or 'unknown'}",
                },
            )
        )
    for relation in snapshot["relations"]:
        if not isinstance(relation, dict) or relation.get("predicate") in SKIPPED_PREDICATES:
            continue
        subject, obj = object_keys.get(relation.get("subject")), object_keys.get(relation.get("object"))
        if subject is None or obj is None or subject == obj:
            continue
        predicate = str(relation.get("predicate"))
        if predicate in REVERSED_PREDICATES:
            subject, obj = obj, subject
            relation_type = REVERSED_PREDICATES[predicate]
        else:
            relation_type = PREDICATE_MAP.get(predicate, "RELATED_TO")
        confidence = relation.get("confidence")
        edges.append(
            MapEdge(
                stable_key=f"{subject}:{predicate}:{obj}"[:700],
                source_stable_key=subject,
                target_stable_key=obj,
                relation_type_id=relation_type,
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                verification_state="unverified",
                source_kind="inferred",
                properties={"cair_predicate": predicate},
            )
        )
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": SOURCE,
            "expected_node_count": len(nodes),
            "expected_edge_count": len(edges),
            "nodes": [node.model_dump() for node in nodes.values()],
            "edges": [edge.model_dump() for edge in edges],
        }
    )


def _attach_evidence(session: Session, export: MapExport) -> int:
    from sion_api import models

    created = 0
    for edge in export.edges:
        if edge.relation_type_id != "EXTRACTED_FROM":
            continue
        relation = session.scalar(select(models.Relation).where(models.Relation.stable_key == edge.stable_key))
        if relation is None:
            continue
        locator = str(edge.properties.get("locator") or "")
        existing = session.scalar(
            select(models.Evidence).where(
                models.Evidence.relation_id == relation.id, models.Evidence.source_locator == locator
            )
        )
        if existing is not None:
            continue
        artifact = session.get(models.Entity, relation.target_entity_id)
        session.add(
            models.Evidence(
                relation_id=relation.id,
                source_uri=(artifact.external_uri if artifact and artifact.external_uri else "urn:aec:cair"),
                source_locator=locator,
                excerpt_hash=None,
                confidence=edge.confidence,
                verification_state="unverified",
                extractor=str(edge.properties.get("extractor") or "aec-cair")[:200],
                properties={"source": export.source, "contract": CONTRACT, "cair_type": edge.properties.get("cair_type")},
            )
        )
        created += 1
    session.commit()
    return created


def ingest_cair_snapshot(session: Session, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Import a CAIR snapshot into the Sion graph (idempotent) and attach evidence."""
    export = cair_snapshot_to_map_export(snapshot)
    result = import_map_export(session, export)
    evidence = _attach_evidence(session, export)
    return {
        "contract": CONTRACT,
        "cair_snapshot_id": snapshot["snapshot_id"],
        "aec_project_id": snapshot["project_id"],
        "created_nodes": result.created_nodes,
        "skipped_nodes": result.skipped_nodes,
        "created_edges": result.created_edges,
        "skipped_edges": result.skipped_edges,
        "evidence_created": evidence,
        "verification_state": "unverified",
    }


def ingest_with_ontology(
    session: Session,
    source: str | Path,
    project_id: str,
    *,
    ontology_root: str | Path | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Run Ontology ingestion for one DXF/IFC file and import the result into Sion."""
    snapshot = run_ontology_ingest(source, project_id, ontology_root=ontology_root, python=python)
    return {"file": str(source), **ingest_cair_snapshot(session, snapshot)}
