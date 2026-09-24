from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sion_api.db import Base, build_engine
from sion_ingestion.agent_bridge import AgentOntologyBridge, AgentSession
from sion_ingestion.bridge_cli import run_cycle
from sion_ingestion.dlp import DLPDecision, scan_payload


def test_synthetic_secret_is_blocked_without_persisting(tmp_path, monkeypatch, capsys):
    session = AgentSession("synthetic-123456789", "codex", "sion_test_secret-abcdef123456", device_id="dev", cwd=str(tmp_path))
    monkeypatch.setattr("sion_ingestion.bridge_cli.PROVIDER_REGISTRY", {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [session])})
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    args = SimpleNamespace(export_out="x.json", pg_out="x.sql", graph_out="x.md", dry_run=True, db_url="sqlite://")
    assert run_cycle(args, ["codex"], None) == 1
    assert not list(tmp_path.iterdir())
    assert "sion_test_secret-abcdef123456" not in capsys.readouterr().out


def test_allowed_payload_is_sanitized_and_sinkable(tmp_path, monkeypatch):
    payload = {"schema": "sion-map-export/v1", "source": "test", "nodes": [], "edges": [], "note": "clean"}
    decision = scan_payload(payload, cwd=tmp_path)
    assert decision.allowed
    assert "clean" in json.dumps(decision.sanitized_payload)


def test_no_sessions_has_explicit_exit_two(monkeypatch):
    monkeypatch.setattr("sion_ingestion.bridge_cli.PROVIDER_REGISTRY", {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [])})
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    args = SimpleNamespace(export_out="x.json", pg_out="x.sql", graph_out="x.md", dry_run=True, db_url="sqlite://")
    assert run_cycle(args, ["codex"], None) == 2


def test_cli_to_db_preserves_tokenized_payload_and_raw_secret_is_not_a_sink(
    tmp_path, monkeypatch
):
    pii_fixture = "cli.person@example.test"
    session = AgentSession(
        "cli-tokenized-123", "codex", f"Contact {pii_fixture}", device_id="dev", cwd=str(tmp_path)
    )
    raw_export = AgentOntologyBridge().convert_sessions_to_map_export([session])
    sanitized = json.loads(
        json.dumps(raw_export.model_dump(by_alias=True), ensure_ascii=False).replace(
            pii_fixture, "[PII:tokenized-cli-value]"
        )
    )
    decision = DLPDecision(
        allowed=False,
        action="tokenized",
        sanitized_payload=sanitized,
        metadata={"trusted_boundary": "test"},
    )
    assert decision.action == "tokenized"

    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "runtime-root"))
    database_path = tmp_path / "bridge.sqlite"
    Base.metadata.create_all(build_engine(f"sqlite:///{database_path}"))
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli.PROVIDER_REGISTRY",
        {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [session])},
    )
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    monkeypatch.setattr("sion_ingestion.bridge_cli.scan_payload", lambda *args, **kwargs: decision)
    monkeypatch.setattr("sion_ingestion.bridge_cli.detect_google_drive_root", lambda: None)
    args = SimpleNamespace(
        export_out="agent_export.json",
        pg_out="agent_graph.sql",
        graph_out="agent_graph.md",
        dry_run=False,
        db_url=f"sqlite:///{tmp_path / 'bridge.sqlite'}",
    )

    assert run_cycle(args, ["codex"], None) == 0
    for path in (tmp_path / "runtime-root").rglob("*"):
        if path.is_file():
            assert pii_fixture not in path.read_text(encoding="utf-8", errors="ignore")
    assert "[PII:" in (tmp_path / "runtime-root" / "agent_export.json").read_text(encoding="utf-8")
