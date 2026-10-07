from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sion_api.main import create_app
from sion_ingestion.document_ingest import build_document_export, extract_text, supported_suffixes
from sion_ingestion.dxf_ingest import parse_dxf

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT / "ontology" / "validation" / "sion-core.shacl.ttl"


def test_ezdxf_parser_matches_fallback(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("PUMP ROOM", dxfattribs={"layer": "A-NOTE"})
    msp.add_mtext("Fire\\Pexit", dxfattribs={"layer": "A-NOTE"})
    msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1)], close=True, dxfattribs={"layer": "A-ROOM"})
    doc.blocks.new("DOOR_BLOCK")
    msp.add_blockref("DOOR_BLOCK", (0, 0), dxfattribs={"layer": "A-DOOR"})
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    items = parse_dxf(path)
    kinds = {(i["kind"], i["name"]) for i in items}
    assert ("annotation", "PUMP ROOM") in kinds
    assert ("block", "DOOR_BLOCK") in kinds
    assert ("segment", "line:A-WALL") in kinds
    assert ("space", "space:A-ROOM") in kinds
    assert any(i["kind"] == "annotation" and "exit" in i["name"] for i in items)

    fallback = {(i["kind"], i["name"]) for i in parse_dxf(path, use_ezdxf=False)}
    assert {("annotation", "PUMP ROOM"), ("segment", "line:A-WALL"), ("space", "space:A-ROOM")} <= fallback


def test_parse_dxf_falls_back_on_unreadable_file(tmp_path):
    path = tmp_path / "broken.dxf"
    path.write_text("0\nSECTION\n2\nENTITIES\n0\nTEXT\n8\nL\n1\nHI\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    assert {"kind": "annotation", "name": "HI", "layer": "L"} in parse_dxf(path)


def test_docx_headings_become_claims(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Structural review", level=1)
    document.add_paragraph("Beam B1 checked.")
    path = tmp_path / "review.docx"
    document.save(path)
    assert ".docx" in supported_suffixes()
    assert extract_text(path).startswith("# Structural review")
    export = build_document_export([path])
    assert export.nodes[0].name == "Structural review"


def test_pdf_text_extraction(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    assert ".pdf" in supported_suffixes()
    assert extract_text(path) == ""
    assert build_document_export([path]).nodes[0].entity_type_id == "Document"


def test_shacl_shapes_parse_and_reject_bad_confidence():
    rdflib = pytest.importorskip("rdflib")
    pytest.importorskip("pyshacl")
    from rdflib import RDF, Literal, Namespace, URIRef

    from sion_ingestion.shacl_validation import SION_NS, validate_graph

    sion = Namespace(SION_NS)
    graph = rdflib.Graph()
    rel = URIRef(SION_NS + "relation/x")
    graph.add((rel, RDF.type, sion.Relation))
    graph.add((rel, sion.source_id, Literal("a")))
    graph.add((rel, sion.target_id, Literal("b")))
    graph.add((rel, sion.relation_type, Literal("RELATED_TO")))
    graph.add((rel, sion.confidence, Literal(1.5)))
    ev = URIRef(SION_NS + "evidence/y")
    graph.add((ev, RDF.type, sion.Evidence))
    graph.add((ev, sion.verification_state, Literal("bogus")))
    report = validate_graph(graph, SHAPES)
    assert not report.conforms
    assert len(report.violations) >= 3  # confidence range, evidence target, state enum


def test_shacl_endpoint_on_ingested_graph(tmp_path):
    pytest.importorskip("pyshacl")
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    client = TestClient(app)
    empty = client.get("/api/v1/validation/shacl")
    assert empty.status_code == 200 and empty.json()["conforms"] is True

    from sion_ingestion.document_ingest import ingest_documents

    note = tmp_path / "note.md"
    note.write_text("# Pump room\n## Valve\n", encoding="utf-8")
    session = app.state.session_factory() if hasattr(app.state, "session_factory") else None
    if session is None:
        pytest.skip("app does not expose session factory")
    with session:
        ingest_documents(session, [note])
    body = client.get("/api/v1/validation/shacl").json()
    assert body["conforms"] is True, body["violations"]
    assert body["triple_count"] > 0
