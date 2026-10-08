"""Relation construction: graph-export conversion, candidate extraction, review API, review UI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_ingestion.graph_export import (
    GraphExportError,
    compare_with_inventory,
    convert_file,
    detect_graphs,
    normalize_relation_type,
)
from sion_ingestion.relation_extraction import (
    Gazetteer,
    KnownEntity,
    TextSpan,
    match_rule,
    proposals_from_lightrag,
    propose_from_spans,
)
from sion_ingestion.relations_cli import main as relations_cli

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "sion-map-production.json"
CONVERTED = ROOT / "data" / "bootstrap" / "sion-map-export.json"
INVENTORY = ROOT / "data" / "bootstrap" / "current-map-inventory.json"
SOURCE_SHA256 = "24f5c46825e8dc223577297cb457d43468bf3a0e6d8a11a6d8050f5fe31dd56f"

WRITE = "write-token-12345678901"
READ = "read-token-123456789012"
AUTH = {"Authorization": f"Bearer {WRITE}"}


def bearer_app(*roots: Path):
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (WRITE, frozenset({"read:knowledge", "write:knowledge"})),
            (READ, frozenset({"read:knowledge"})),
        ),
    )
    return create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy, ingest_roots=list(roots))


def import_production_map(c: TestClient) -> dict:
    r = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_node_count": 31, "expected_edge_count": 43}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- the Sion Map export


def test_production_map_source_is_byte_identical_and_complete():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    export, report = convert_file(SOURCE, expected_nodes=31, expected_edges=43)
    assert report.format == "ontology-map-export" and report.issues == []
    assert report.relation_type_counts["VALIDATES"] == 3
    inventory = compare_with_inventory(export, json.loads(INVENTORY.read_text(encoding="utf-8")))
    assert inventory["matches"] is True
    assert inventory["missing_labels"] == [] and inventory["extra_labels"] == []
    assert inventory["category_mismatches"] == {}
    # every edge is an unverified candidate that points back to its line in the source
    for i, edge in enumerate(export.edges):
        assert edge.verification_state == "unverified" and edge.properties["candidate"] is True
        assert edge.properties["provenance"]["source_sha256"] == SOURCE_SHA256
        assert edge.properties["provenance"]["locator"] == f"$.relations[{i}]"
    raw = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    by_id = {n["id"]: n["label"] for n in raw["nodes"]}
    names = {n.stable_key: n.name for n in export.nodes}
    assert sorted((by_id[r["source_id"]], r["relation_type_id"], by_id[r["target_id"]]) for r in raw["relations"]) == sorted(
        (names[e.source_stable_key], e.relation_type_id, names[e.target_stable_key]) for e in export.edges
    )


def test_committed_conversion_matches_source():
    export, _ = convert_file(SOURCE, expected_nodes=31, expected_edges=43)
    committed = json.loads(CONVERTED.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(export.model_dump(by_alias=True)))


def test_import_production_map_via_api_is_idempotent_and_reviewable():
    with TestClient(bearer_app(ROOT / "data"), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        body = import_production_map(c)
        assert body["import"] == {"created_nodes": 31, "skipped_nodes": 0, "created_edges": 43, "skipped_edges": 0}
        assert body["evidence_created"] == 43
        assert body["inventory"]["matches"] is True
        again = import_production_map(c)
        assert again["import"]["created_edges"] == 0 and again["evidence_created"] == 0
        graph = c.get("/api/v1/graph", headers=AUTH).json()
        assert graph["node_count"] == 31 and graph["edge_count"] == 43
        assert {e["verification_state"] for e in graph["edges"]} == {"unverified"}
        pending = c.get("/api/v1/relations/candidates", headers=AUTH).json()
        assert pending["total"] == 43 and pending["counts"] == {"pending": 43, "approved": 0, "rejected": 0}
        first = pending["candidates"][0]
        assert first["provenance"]["source_sha256"] == SOURCE_SHA256
        assert first["evidence"][0]["source_locator"].startswith("$.relations[")


def test_dry_run_and_count_mismatch():
    with TestClient(bearer_app(ROOT / "data"), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        dry = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "dry_run": True}, headers=AUTH).json()
        assert dry["report"]["edge_count"] == 43 and "import" not in dry
        assert c.get("/api/v1/graph", headers=AUTH).json()["edge_count"] == 0
        bad = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_edge_count": 44}, headers=AUTH)
        assert bad.status_code == 422 and "edge count mismatch" in bad.json()["detail"]
        outside = c.post("/api/v1/import/graph-export", json={"path": "/etc/hosts"}, headers=AUTH)
        assert outside.status_code == 403


# --------------------------------------------------------------------------- format parsers


def _single(text: str, suffix: str):
    graphs = detect_graphs(text, suffix=suffix)
    assert len(graphs) >= 1
    return max(graphs, key=lambda g: len(g.edges))


def test_d3_json_with_object_endpoints():
    doc = {"nodes": [{"id": "a", "name": "Alpha", "group": "core"}, {"id": "b", "name": "Beta"}],
           "links": [{"source": {"id": "a"}, "target": "b", "type": "uses"}]}
    g = _single(json.dumps(doc), ".json")
    assert g.format == "d3" and [(e.source, e.target, e.label) for e in g.edges] == [("a", "b", "uses")]


def test_vis_dataset_in_html_script():
    page = """<html><body><div id="net"></div><script>
      var nodes = new vis.DataSet([{id: 1, label: 'CAD Bridge'}, {id: 2, label: "DWG / DXF"},]);
      var edges = new vis.DataSet([{from: 1, to: 2, label: 'USES'}]);
      new vis.Network(document.getElementById('net'), {nodes, edges}, {});
    </script></body></html>"""
    g = _single(page, ".html")
    assert g.format == "vis"
    assert [n.label for n in g.nodes] == ["CAD Bridge", "DWG / DXF"]
    assert [(e.source, e.target, e.label) for e in g.edges] == [("1", "2", "USES")]


def test_cytoscape_elements_list_and_json_script_block():
    elements = [{"data": {"id": "x", "label": "X"}}, {"data": {"id": "y", "label": "Y"}},
                {"data": {"id": "e1", "source": "x", "target": "y", "label": "depends on"}}]
    page = f'<html><script type="application/json" id="graph">{json.dumps({"elements": elements})}</script></html>'
    g = _single(page, ".html")
    assert g.format == "cytoscape" and g.edges[0].label == "depends on"
    assert normalize_relation_type("depends on") == ("DEPENDS_ON", "depends on")


def test_const_nodes_links_in_script():
    page = """<script>
      const nodes = [{ id: "n1", label: "Ontology Store" }, { id: "n2", label: "Supabase / Postgres" }];
      const links = [{ source: "n1", target: "n2", relation: "DEPENDS_ON" }];
    </script>"""
    g = _single(page, ".htm")
    assert [(e.source, e.target, e.label) for e in g.edges] == [("n1", "n2", "DEPENDS_ON")]


def test_mermaid_in_markdown(tmp_path):
    md = tmp_path / "flow.md"
    md.write_text("# Map\n```mermaid\nflowchart LR\n  A[Agent Orchestrator] -->|uses| B[DeepSeek Planner]\n"
                  "  A --> C((MCP Mesh))\n  C -- connects to --> D{CAD Bridge}\n  E[Isolated]\n```\n", encoding="utf-8")
    export, report = convert_file(md, namespace="demo")
    assert report.format == "mermaid" and report.node_count == 5 and report.edge_count == 3
    types = sorted(e.relation_type_id for e in export.edges)
    assert types == ["CONNECTS_TO", "RELATED_TO", "USES"]
    assert {n.name for n in export.nodes} >= {"Agent Orchestrator", "DeepSeek Planner", "MCP Mesh", "CAD Bridge", "Isolated"}


def test_graphml(tmp_path):
    graphml = tmp_path / "g.graphml"
    graphml.write_text("""<?xml version="1.0"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="label"/><key id="d1" for="edge" attr.name="type"/>
  <graph edgedefault="directed">
    <node id="n0"><data key="d0">Drawing Index</data></node>
    <node id="n1"><data key="d0">Ontology Store</data></node>
    <edge id="e0" source="n0" target="n1"><data key="d1">PART_OF</data></edge>
  </graph>
</graphml>""", encoding="utf-8")
    export, report = convert_file(graphml)
    assert report.format == "graphml" and export.edges[0].relation_type_id == "PART_OF"


def test_bad_edges_are_reported_not_repaired(tmp_path):
    doc = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "a"}],
           "links": [{"source": "a", "target": "b", "type": "USES"}, {"source": "a", "target": "b", "type": "uses"},
                     {"source": "a", "target": "a", "type": "USES"}, {"source": "a", "target": "zz"}]}
    path = tmp_path / "g.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    export, report = convert_file(path)
    assert report.edge_count == 1 and report.node_count == 2
    joined = " ".join(report.issues)
    assert "duplicate node id" in joined and "duplicate edge" in joined and "self-loop" in joined and "undeclared" in joined
    with pytest.raises(GraphExportError):
        convert_file(path, expected_edges=4)
    (tmp_path / "empty.json").write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(GraphExportError):
        convert_file(tmp_path / "empty.json")


# --------------------------------------------------------------------------- extraction rules


def _gaz(*names: str) -> Gazetteer:
    return Gazetteer([(KnownEntity(i, f"k:{n}", n), [n]) for i, n in enumerate(names)])


def test_rules_english_korean_and_reverse():
    assert match_rule(" uses the ", "")[:2] == ("USES", "forward")
    assert match_rule(" is validated by ", "")[:2] == ("VALIDATES", "reverse")
    assert match_rule(" contains ", "")[:2] == ("PART_OF", "reverse")
    assert match_rule("는 ", "를 검증한다.")[:2] == ("VALIDATES", "forward")
    assert match_rule("는 ", "에 의존한다")[:2] == ("DEPENDS_ON", "forward")
    assert match_rule("는 ", "의 일부이다")[:2] == ("PART_OF", "forward")
    assert match_rule(" and maybe something unrelated ", "") is None
    gaz = _gaz("Agent Orchestrator", "DeepSeek Planner", "Cross Validation", "Ontology Store", "Drive Mirror")
    spans = [TextSpan("file:///a.md", "", "Agent Orchestrator uses DeepSeek Planner. Cross Validation는 Ontology Store를 검증한다.\n"
                      "Drive Mirror and Ontology Store were discussed.\nLater, Drive Mirror sat next to Ontology Store again.")]
    proposals = {p.triple: p for p in propose_from_spans(spans, gaz)}
    uses = proposals[("k:Agent Orchestrator", "USES", "k:DeepSeek Planner")]
    assert uses.confidence == 0.6 and uses.evidence[0].locator == "line:1:0-41"
    assert uses.evidence[0].excerpt == "Agent Orchestrator uses DeepSeek Planner."
    assert ("k:Cross Validation", "VALIDATES", "k:Ontology Store") in proposals
    co = proposals[("k:Drive Mirror", "RELATED_TO", "k:Ontology Store")]
    assert co.rule == "co-occurrence" and len(co.evidence) == 2
    # single co-occurrence below the threshold -> nothing
    once = propose_from_spans([TextSpan("u", "", "Drive Mirror with Ontology Store.")], gaz)
    assert once == []


def test_lightrag_graph_conversion():
    gaz = _gaz("CAD Bridge", "DWG / DXF")
    kg = {"nodes": [{"id": "CAD Bridge", "labels": ["CAD Bridge"], "properties": {"entity_id": "CAD Bridge"}},
                    {"id": "dwg / dxf", "labels": [], "properties": {"entity_id": "DWG / DXF"}},
                    {"id": "Unknown", "labels": [], "properties": {}}],
          "edges": [{"id": "e1", "type": "DIRECTED", "source": "CAD Bridge", "target": "dwg / dxf",
                     "properties": {"keywords": "reads, uses", "description": "CAD Bridge reads DWG files", "source_id": "chunk-1", "file_path": "notes.md"}},
                    {"id": "e2", "source": "CAD Bridge", "target": "Unknown", "properties": {}}]}
    proposals, notes = proposals_from_lightrag(kg, gaz, workspace="w", model="m")
    assert [(p.relation_type_id, p.rule, p.model) for p in proposals] == [("USES", "lightrag", "m")]
    assert proposals[0].evidence[0].source_uri == "lightrag://w/notes.md"
    assert "1 edges skipped" in notes[0]


# --------------------------------------------------------------------------- end-to-end extraction + review

DOC = """# Platform notes
Agent Orchestrator uses DeepSeek Planner.
Cross Validation는 Ontology Store를 검증한다.
Drive Mirror and Supabase / Postgres were both mentioned here.
The Drive Mirror job runs after Supabase / Postgres backups.
"""


def test_extract_review_approve_reject_flow(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text(DOC, encoding="utf-8")
    dxf = tmp_path / "plan.dxf"
    dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nTEXT\n8\nA-NOTE\n1\nCAD Bridge input\n0\nLINE\n8\nA-WALL\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    with TestClient(bearer_app(ROOT / "data", tmp_path), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        import_production_map(c)
        assert c.post("/api/v1/ingest/dxf", json={"path": str(dxf)}, headers=AUTH).status_code == 200
        r = c.post("/api/v1/extract/relations", json={"paths": [str(doc), str(dxf)]}, headers=AUTH)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["known_entities"] == 31
        assert body["proposals_by_extractor"] == {"co-occurrence": 1, "dxf-mention": 1, "en": 1, "ko": 1}
        # "Agent Orchestrator USES DeepSeek Planner" and "Cross Validation VALIDATES Ontology Store" are
        # already among the 43 imported candidates: the new evidence is attached to them, no duplicates
        assert body["candidates_created"] == 2 and body["candidates_updated"] == 2
        again = c.post("/api/v1/extract/relations", json={"paths": [str(doc), str(dxf)]}, headers=AUTH).json()
        assert again["candidates_created"] == 0 and again["evidence_created"] == 0

        pending = c.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
        assert pending["total"] == 45
        by_triple = {(x["source"]["name"], x["relation_type_id"], x["target"]["name"]): x for x in pending["candidates"]}
        uses = by_triple[("Agent Orchestrator", "USES", "DeepSeek Planner")]
        assert uses["evidence_count"] == 2
        span = next(e for e in uses["evidence"] if e["extractor"] == "sion-relation-extractor/v1")
        assert span["excerpt"] == "Agent Orchestrator uses DeepSeek Planner."
        assert span["source_locator"] == "line:2:0-41" and span["source_uri"].endswith("/notes.md")
        validates = by_triple[("Cross Validation", "VALIDATES", "Ontology Store")]
        assert validates["evidence_count"] == 2
        assert ("plan.dxf", "REFERENCES", "CAD Bridge") in by_triple
        related = by_triple[("Drive Mirror", "RELATED_TO", "Supabase / Postgres")]
        assert related["confidence"] == 0.25

        # read-only token cannot decide
        assert c.post(f"/api/v1/relations/candidates/{uses['id']}/approve", json={}, headers={"Authorization": f"Bearer {READ}"}).status_code == 403
        assert c.post(f"/api/v1/relations/candidates/{uses['id']}/approve", json={}).status_code == 401

        ok = c.post(f"/api/v1/relations/candidates/{uses['id']}/approve", json={"reviewer": "khs", "note": "checked"}, headers=AUTH)
        assert ok.status_code == 200, ok.text
        approved = ok.json()
        assert approved["status"] == "approved" and approved["verification_state"] == "human_verified"
        assert approved["review"]["reviewer"] == "khs" and approved["review"]["previous_state"] == "unverified"
        assert {e["verification_state"] for e in approved["evidence"]} == {"human_verified"}
        assert approved["rules"] == ["en:uses:forward"] and approved["provenance"]["source_edge_id"] == "rel-23"
        assert c.post(f"/api/v1/relations/candidates/{uses['id']}/reject", json={}, headers=AUTH).status_code == 409

        rej = c.post(f"/api/v1/relations/candidates/{related['id']}/reject", json={"note": "co-occurrence only"}, headers=AUTH)
        assert rej.status_code == 200 and rej.json()["status"] == "rejected"
        graph = c.get("/api/v1/graph", headers=AUTH).json()
        assert related["id"] not in {e["id"] for e in graph["edges"]}
        assert related["id"] in {e["id"] for e in c.get("/api/v1/graph?include_rejected=true", headers=AUTH).json()["edges"]}
        assert {e["verification_state"] for e in graph["edges"] if e["id"] == uses["id"]} == {"human_verified"}

        # a rejected candidate is not re-proposed, an approved one is not touched
        third = c.post("/api/v1/extract/relations", json={"paths": [str(doc)]}, headers=AUTH).json()
        reasons = {s["reason"] for s in third["skipped"]}
        assert "already reviewed (rejected)" in reasons and "already reviewed (human_verified)" in reasons

        counts = c.get("/api/v1/relations/candidates?status=all", headers=AUTH).json()["counts"]
        assert counts == {"pending": 43, "approved": 1, "rejected": 1}
        detail = c.get(f"/api/v1/relations/candidates/{validates['id']}", headers=AUTH).json()
        assert {e["extractor"] for e in detail["evidence"]} == {"sion-graph-export/v1", "sion-relation-extractor/v1"}


def test_review_errors_and_non_candidates():
    with TestClient(bearer_app(), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        a = c.post("/api/v1/entities", json={"stable_key": "p:a", "entity_type_id": "Project", "name": "A"}, headers=AUTH).json()
        b = c.post("/api/v1/entities", json={"stable_key": "p:b", "entity_type_id": "Tool", "name": "B"}, headers=AUTH).json()
        rel = c.post("/api/v1/relations", json={"stable_key": "p:a:USES:p:b", "source_entity_id": a["id"], "target_entity_id": b["id"],
                                                 "relation_type_id": "USES", "verification_state": "human_verified"}, headers=AUTH).json()
        assert c.post(f"/api/v1/relations/candidates/{rel['id']}/approve", json={}, headers=AUTH).status_code == 409
        assert c.get(f"/api/v1/relations/candidates/{rel['id']}", headers=AUTH).status_code == 409
        missing = "00000000-0000-0000-0000-000000000000"
        assert c.post(f"/api/v1/relations/candidates/{missing}/approve", json={}, headers=AUTH).status_code == 404
        assert c.get("/api/v1/relations/candidates?status=bogus", headers=AUTH).status_code == 422
        assert c.get("/api/v1/relations/candidates", headers=AUTH).json()["total"] == 0
        # VALIDATES is a core relation type now
        v = c.post("/api/v1/relations", json={"stable_key": "p:b:VALIDATES:p:a", "source_entity_id": b["id"], "target_entity_id": a["id"],
                                               "relation_type_id": "VALIDATES"}, headers=AUTH)
        assert v.status_code == 201, v.text


def test_ifc_structure_candidates(tmp_path):
    ifc = tmp_path / "m.ifc"
    ifc.write_text("""ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('m.ifc','2026-10-08T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'Demo Project',$,$,$,$,$,$);
#10=IFCBUILDINGSTOREY('2dQFggKBb1fOc1CqZDIDlx',$,'Level 1',$,$,$,$,$,.ELEMENT.,0.);
#20=IFCWALL('3vB2YO$MX4xv5uCqZZG05x',$,'Wall A',$,$,$,$,$,$);
#21=IFCDOOR('1hOSvn6df7F8_7GcBWlRGQ',$,'Door 01',$,$,$,$,$,$,$,$);
#40=IFCRELCONTAINEDINSPATIALSTRUCTURE('0Lm5Xq1Nn3Yv8pZ2uQ7rS1',$,'Storey contents',$,(#20,#21),#10);
#41=IFCRELAGGREGATES('2Kx9TqE1v0Nh4sY6wB3cD8',$,$,$,#1,(#10));
ENDSEC;
END-ISO-10303-21;
""", encoding="utf-8")
    with TestClient(bearer_app(tmp_path), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        before = c.post("/api/v1/extract/relations", json={"paths": [str(ifc)]}, headers=AUTH).json()
        assert before["candidates_created"] == 0 and "model not ingested" in before["notes"][0]
        assert c.post("/api/v1/ingest/ifc", json={"path": str(ifc)}, headers=AUTH).status_code == 200
        body = c.post("/api/v1/extract/relations", json={"paths": [str(ifc)]}, headers=AUTH).json()
        assert body["proposals_by_extractor"] == {"ifc-structure": 3}
        assert body["candidates_created"] == 3
        cands = c.get("/api/v1/relations/candidates", headers=AUTH).json()["candidates"]
        triples = {(x["source"]["name"], x["relation_type_id"], x["target"]["name"]) for x in cands}
        assert triples == {("Wall A", "PART_OF", "Level 1"), ("Door 01", "PART_OF", "Level 1"), ("Level 1", "PART_OF", "Demo Project")}
        assert {x["evidence"][0]["source_locator"] for x in cands} == {"ifc:#40", "ifc:#41"}


@pytest.mark.parametrize("route", ["/api/v1/extract/relations", "/api/v1/import/graph-export",
                                   "/api/v1/relations/candidates/00000000-0000-0000-0000-000000000000/approve",
                                   "/api/v1/relations/candidates/00000000-0000-0000-0000-000000000000/reject",
                                   "/api/v1/graphrag/extract-relations"])
def test_new_write_routes_require_write_scope(route):
    with TestClient(bearer_app(), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        assert c.post(route, json={}).status_code == 401
        assert c.post(route, json={}, headers={"Authorization": f"Bearer {READ}"}).status_code == 403


def test_review_page_and_map_page_served():
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        page = c.get("/review")
        assert page.status_code == 200 and "/api/v1/relations/candidates" in page.text
        assert "/approve" not in page.text or "${action}" in page.text
        m = c.get("/map").text
        assert "edge.source" in m and "edge.source_entity_id" not in m and 'href="review"' in m


def test_cli_convert_import_extract(tmp_path, capsys):
    out = tmp_path / "export.json"
    assert relations_cli(["convert", str(SOURCE), "-o", str(out), "--expect-nodes", "31", "--expect-edges", "43"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["expected_edge_count"] == 43
    db = f"sqlite:///{tmp_path / 'sion.db'}"
    assert relations_cli(["import", str(out), "--database-url", db]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["import"]["created_edges"] == 43 and imported["evidence_created"] == 43
    doc = tmp_path / "n.md"
    doc.write_text("MCP Mesh uses Browser Control.\n", encoding="utf-8")
    assert relations_cli(["extract", str(doc), "--database-url", db]) == 0
    extracted = json.loads(capsys.readouterr().out)
    # MCP Mesh USES Browser Control is already among the 43 -> evidence is added to it
    assert extracted["candidates_created"] == 0 and extracted["candidates_updated"] == 1
    assert relations_cli(["candidates", "--database-url", db, "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["pending"] == 43
    assert relations_cli(["convert", str(SOURCE), "--expect-edges", "40"]) == 2
