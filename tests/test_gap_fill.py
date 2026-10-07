from pathlib import Path

from sion_ingestion.agent_bridge import DeepSeekReader, HermesReader, ZCodeReader
from sion_ingestion.document_ingest import build_document_export
from sion_ingestion.dxf_ingest import parse_dxf


def test_local_readers_use_override(tmp_path, monkeypatch):
    log = tmp_path / "session.jsonl"
    log.write_text('{"role":"user","content":"fix ontology gap"}\n{"role":"tool","tool_name":"read_file"}\n', encoding="utf-8")
    monkeypatch.setenv("SION_DEEPSEEK_ROOT", str(tmp_path))
    sessions = DeepSeekReader().discover()
    assert sessions and sessions[0].provider == "deepseek"
    assert "read_file" in sessions[0].tools


def test_hermes_and_zcode_empty_without_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SION_HERMES_ROOT", str(tmp_path / "missing-h"))
    monkeypatch.setenv("SION_ZCODE_ROOT", str(tmp_path / "missing-z"))
    assert HermesReader().discover() == []
    assert ZCodeReader().discover() == []


def test_document_export_extracts_heading(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("# Pump room\nwall note\n", encoding="utf-8")
    export = build_document_export([path])
    assert export.expected_node_count == 2
    assert export.edges[0].relation_type_id == "EXTRACTED_FROM"
    assert export.edges[0].verification_state == "unverified"


def test_dxf_parser_reads_text_and_insert(tmp_path):
    path = tmp_path / "plan.dxf"
    path.write_text("0\nSECTION\n2\nENTITIES\n0\nTEXT\n8\nA-NOTE\n1\nDOOR\n0\nINSERT\n8\nA-DOOR\n2\nDOOR_BLOCK\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    items = parse_dxf(path)
    assert {item["kind"] for item in items} == {"annotation", "block"}
