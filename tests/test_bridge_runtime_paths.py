from __future__ import annotations

from types import SimpleNamespace

import pytest

from sion_ingestion.agent_bridge import AgentSession
from sion_ingestion.bridge_cli import _data_root, _runtime_path, run_cycle
from sion_ingestion.dlp import DLPDecision


def _args(tmp_path, **overrides):
    values = {
        "export_out": "export.json",
        "pg_out": "export.sql",
        "graph_out": "export.md",
        "dry_run": True,
        "db_url": "sqlite://",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _provider(monkeypatch, tmp_path):
    session = AgentSession("synthetic-123456789", "codex", "clean", device_id="dev", cwd=str(tmp_path))
    monkeypatch.setattr("sion_ingestion.bridge_cli.PROVIDER_REGISTRY", {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [session])})
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    monkeypatch.setattr("sion_ingestion.bridge_cli.detect_google_drive_root", lambda: None)


def test_allowed_dry_run_cycle_creates_no_json_sql_markdown_or_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _provider(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli.scan_payload",
        lambda payload, cwd: DLPDecision(True, "allowed", payload),
    )
    assert run_cycle(_args(tmp_path), ["codex"], None) == 0
    assert list(tmp_path.iterdir()) == []


def test_runtime_paths_reject_escape_and_parent_segments(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    root = _data_root()
    with pytest.raises(ValueError):
        _runtime_path("../escape.json", root)
    with pytest.raises(ValueError):
        _runtime_path(tmp_path.parent / "escape.json", root)


def test_default_outputs_are_contained_by_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    root = _data_root()
    assert _runtime_path("runtime/export.json", root).is_relative_to(root)
    assert _runtime_path("runtime/sion.db", root).is_relative_to(root)
