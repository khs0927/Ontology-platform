"""SHACL validation of the Sion graph against ``ontology/validation/sion-core.shacl.ttl``.

rdflib (BSD-3-Clause) and pyshacl (Apache-2.0) come from the optional
``validation`` extra and are imported only when a validation runs. The graph
is projected read-only from the database: entities, relations and evidence
become ``sion:Entity`` / ``sion:Relation`` / ``sion:Evidence`` nodes with the
properties the shapes constrain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sion_core import MissingExtra, require
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sion_api import models

SION_NS = "https://sion-jesus.xyz/ontology/core/"
SHAPES_ENV = "SION_SHACL_SHAPES"
MAX_VIOLATIONS = 200


class ShaclUnavailable(RuntimeError):
    """rdflib/pyshacl not installed, or the shapes file is missing."""


@dataclass
class ShaclReport:
    conforms: bool
    triple_count: int
    counts: dict[str, int]
    truncated: bool
    violations: list[dict[str, Any]] = field(default_factory=list)


def shapes_path(ontology_path: Path) -> Path:
    """``SION_SHACL_SHAPES`` or ``<ontology root>/validation/sion-core.shacl.ttl``."""
    override = os.environ.get(SHAPES_ENV)
    if override:
        return Path(override).expanduser()
    return ontology_path.resolve().parent.parent / "validation" / "sion-core.shacl.ttl"


def _libs():
    try:
        return require("rdflib", extra="validation"), require("pyshacl", extra="validation")
    except MissingExtra as exc:
        raise ShaclUnavailable(str(exc)) from exc


def session_to_graph(session: Session, *, limit: int) -> tuple[Any, dict[str, int], bool]:
    """Project up to ``limit`` rows per table into an rdflib graph."""
    rdflib, _ = _libs()
    from rdflib import RDF, Literal, Namespace, URIRef
    from rdflib.namespace import XSD

    sion = Namespace(SION_NS)
    graph = rdflib.Graph()
    graph.bind("sion", sion)

    def node(kind: str, ident: Any) -> URIRef:
        return URIRef(f"{SION_NS}{kind}/{ident}")

    def text(value: Any) -> Literal:
        return Literal(str(value), datatype=XSD.string)

    counts = {"entities": 0, "relations": 0, "evidence": 0}
    for entity in session.scalars(select(models.Entity).order_by(models.Entity.id).limit(limit)):
        subject = node("entity", entity.id)
        graph.add((subject, RDF.type, sion.Entity))
        graph.add((subject, sion.id, text(entity.id)))
        if entity.name is not None:
            graph.add((subject, sion.name, text(entity.name)))
        counts["entities"] += 1
    for relation in session.scalars(select(models.Relation).order_by(models.Relation.id).limit(limit)):
        subject = node("relation", relation.id)
        graph.add((subject, RDF.type, sion.Relation))
        graph.add((subject, sion.source_id, text(relation.source_entity_id)))
        graph.add((subject, sion.target_id, text(relation.target_entity_id)))
        graph.add((subject, sion.relation_type, text(relation.relation_type_id)))
        if relation.confidence is not None:
            graph.add((subject, sion.confidence, Literal(float(relation.confidence), datatype=XSD.double)))
        counts["relations"] += 1
    for evidence in session.scalars(select(models.Evidence).order_by(models.Evidence.id).limit(limit)):
        subject = node("evidence", evidence.id)
        graph.add((subject, RDF.type, sion.Evidence))
        if evidence.relation_id is not None:
            graph.add((subject, sion.relation_id, text(evidence.relation_id)))
        if evidence.entity_id is not None:
            graph.add((subject, sion.entity_id, text(evidence.entity_id)))
        if evidence.verification_state is not None:
            graph.add((subject, sion.verification_state, Literal(evidence.verification_state)))
        counts["evidence"] += 1
    totals = {
        "entities": session.scalar(select(func.count()).select_from(models.Entity)) or 0,
        "relations": session.scalar(select(func.count()).select_from(models.Relation)) or 0,
        "evidence": session.scalar(select(func.count()).select_from(models.Evidence)) or 0,
    }
    truncated = any(totals[key] > counts[key] for key in counts)
    return graph, counts, truncated


def validate_graph(data_graph: Any, shapes: Path) -> tuple[bool, list[dict[str, Any]]]:
    rdflib, pyshacl = _libs()
    from rdflib import Namespace
    from rdflib.namespace import RDF

    if not shapes.is_file():
        raise ShaclUnavailable(f"SHACL shapes file not found: {shapes.name} (set {SHAPES_ENV})")
    shapes_graph = rdflib.Graph().parse(str(shapes), format="turtle")
    conforms, results, _text = pyshacl.validate(data_graph, shacl_graph=shapes_graph, inference="none")
    sh = Namespace("http://www.w3.org/ns/shacl#")
    violations = []
    for result in results.subjects(RDF.type, sh.ValidationResult):
        violations.append({
            "focus_node": str(results.value(result, sh.focusNode)),
            "path": str(results.value(result, sh.resultPath) or ""),
            "severity": str(results.value(result, sh.resultSeverity) or "").rsplit("#", 1)[-1],
            "constraint": str(results.value(result, sh.sourceConstraintComponent) or "").rsplit("#", 1)[-1],
            "message": str(results.value(result, sh.resultMessage) or ""),
        })
    violations.sort(key=lambda v: (v["focus_node"], v["path"], v["constraint"]))
    return bool(conforms), violations


def validate_session(session: Session, shapes: Path, *, limit: int = 10_000) -> ShaclReport:
    graph, counts, truncated = session_to_graph(session, limit=limit)
    conforms, violations = validate_graph(graph, shapes)
    return ShaclReport(conforms, len(graph), counts, truncated, violations)
