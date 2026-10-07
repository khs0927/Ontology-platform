"""SHACL validation of the knowledge graph against ontology/validation/sion-core.shacl.ttl.

Uses rdflib (BSD-3) and pyshacl (Apache-2.0), installed via the ``validation`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_api import models

SION_NS = "https://sion-jesus.xyz/ontology/core/"
DEFAULT_SHAPES = Path(__file__).resolve().parents[3] / "ontology" / "validation" / "sion-core.shacl.ttl"


class ShaclUnavailable(RuntimeError):
    pass


@dataclass
class ShaclReport:
    conforms: bool
    triple_count: int
    violations: list[dict] = field(default_factory=list)
    text: str = ""


def _require():
    try:
        import pyshacl
        import rdflib
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise ShaclUnavailable("install the 'validation' extra: pip install -e .[validation]") from exc
    return rdflib, pyshacl


def session_to_graph(session: Session, *, limit: int | None = None):
    rdflib, _ = _require()
    from rdflib import RDF, Literal, Namespace, URIRef
    from rdflib.namespace import XSD

    sion = Namespace(SION_NS)
    graph = rdflib.Graph()
    graph.bind("sion", sion)

    def node(kind: str, ident) -> URIRef:
        return URIRef(f"{SION_NS}{kind}/{ident}")

    for entity in session.scalars(select(models.Entity).limit(limit)):
        subject = node("entity", entity.id)
        graph.add((subject, RDF.type, sion.Entity))
        graph.add((subject, sion.id, Literal(str(entity.id), datatype=XSD.string)))
        graph.add((subject, sion.name, Literal(entity.name, datatype=XSD.string)))
    for relation in session.scalars(select(models.Relation).limit(limit)):
        subject = node("relation", relation.id)
        graph.add((subject, RDF.type, sion.Relation))
        graph.add((subject, sion.source_id, Literal(str(relation.source_entity_id), datatype=XSD.string)))
        graph.add((subject, sion.target_id, Literal(str(relation.target_entity_id), datatype=XSD.string)))
        graph.add((subject, sion.relation_type, Literal(relation.relation_type_id, datatype=XSD.string)))
        if relation.confidence is not None:
            graph.add((subject, sion.confidence, Literal(float(relation.confidence))))
    for evidence in session.scalars(select(models.Evidence).limit(limit)):
        subject = node("evidence", evidence.id)
        graph.add((subject, RDF.type, sion.Evidence))
        if evidence.relation_id is not None:
            graph.add((subject, sion.relation_id, Literal(str(evidence.relation_id))))
        if evidence.entity_id is not None:
            graph.add((subject, sion.entity_id, Literal(str(evidence.entity_id))))
        graph.add((subject, sion.verification_state, Literal(evidence.verification_state)))
    return graph


def validate_graph(data_graph, shapes_path: Path = DEFAULT_SHAPES) -> ShaclReport:
    rdflib, pyshacl = _require()
    from rdflib import Namespace
    from rdflib.namespace import RDF

    shapes = rdflib.Graph().parse(str(shapes_path), format="turtle")
    conforms, results_graph, text = pyshacl.validate(data_graph, shacl_graph=shapes, inference="none")
    sh = Namespace("http://www.w3.org/ns/shacl#")
    violations = []
    for result in results_graph.subjects(RDF.type, sh.ValidationResult):
        violations.append({
            "focus_node": str(results_graph.value(result, sh.focusNode)),
            "path": str(results_graph.value(result, sh.resultPath) or ""),
            "message": str(results_graph.value(result, sh.resultMessage) or ""),
        })
    return ShaclReport(conforms=bool(conforms), triple_count=len(data_graph), violations=violations, text=text)


def validate_session(session: Session, shapes_path: Path = DEFAULT_SHAPES, *, limit: int | None = None) -> ShaclReport:
    return validate_graph(session_to_graph(session, limit=limit), shapes_path)
