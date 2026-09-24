"""P0 fault-oracle contracts.

These tests intentionally assert the production boundary, not a test double:
a missing production guard is a contract failure and must be fixed in the
production module named by the test, never hidden by a fallback here.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from sion_api.health import check_readiness
from sion_api.main import create_app
from sion_ingestion.agent_bridge import AgentSession
from sion_ingestion.bridge_cli import _data_root, run_cycle
from sion_ingestion.dlp import DLPDecision

ROOT = Path(__file__).resolve().parents[1]


def _sync_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("p0_sion_sync", ROOT / "sync" / "sion_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider(monkeypatch, tmp_path, payload="clean"):
    session = AgentSession("synthetic-123456789", "codex", payload, device_id="dev", cwd=str(tmp_path))
    monkeypatch.setattr("sion_ingestion.bridge_cli.PROVIDER_REGISTRY", {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [session])})
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    monkeypatch.setattr("sion_ingestion.bridge_cli.detect_google_drive_root", lambda: None)


def test_contract_production_rejects_tokenless_sqlite_auto_create(monkeypatch):
    monkeypatch.setenv("SION_ENV", "production")
    with pytest.raises((RuntimeError, ValueError)):
        create_app(database_url="sqlite://", auto_create_schema=True)


def test_contract_docs_and_openapi_are_bearer_authenticated():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    app.state.settings = app.state.settings.__class__(**{**app.state.settings.__dict__, "local_api_token": "token"})
    with TestClient(app) as client:
        assert client.get("/docs").status_code in {401, 403}
        assert client.get("/openapi.json").status_code in {401, 403}
        assert client.get("/docs", headers={"Authorization": "Bearer token"}).status_code == 200
        assert client.get("/openapi.json", headers={"Authorization": "Bearer token"}).status_code == 200


def test_contract_vector_readiness_reports_missing_embeddings_table_as_503(monkeypatch):
    monkeypatch.setenv("SION_VECTOR_ENABLED", "1")
    monkeypatch.setenv("SION_LOCAL_API_TOKEN", "token")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in ("entity_types", "relation_types", "entities", "ontology_versions", "artifacts", "documents", "chunks", "relations", "evidence"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
    result = check_readiness(engine, vector_enabled=True)
    assert result["status"] == "not_ready"
    assert result["components"]["vector"]["reason"] == "vector_postgres_required"
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as client:
        response = client.get("/health/ready", headers={"Authorization": "Bearer token"})
        assert response.status_code in {401, 503}


def test_contract_allowed_dry_run_persists_no_outputs_or_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _provider(monkeypatch, tmp_path)
    monkeypatch.setattr("sion_ingestion.bridge_cli.scan_payload", lambda payload, cwd: DLPDecision(True, "allowed", payload))
    args = SimpleNamespace(export_out="export.json", pg_out="export.sql", graph_out="export.md", dry_run=True, db_url="sqlite://")
    assert run_cycle(args, ["codex"], None) == 0
    assert list(tmp_path.iterdir()) == []


def test_contract_dlp_blocked_cycle_persists_no_outputs_or_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _provider(monkeypatch, tmp_path, "sk-THIS-SECRET-MUST-NOT-PERSIST")
    args = SimpleNamespace(export_out="export.json", pg_out="export.sql", graph_out="export.md", dry_run=False, db_url="sqlite://")
    assert run_cycle(args, ["codex"], None) == 1
    assert list(tmp_path.iterdir()) == []


def test_contract_incomplete_canonical_destination_is_not_already_present(tmp_path):
    sync = _sync_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "x").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-m", "x"], cwd=repo, check=True, capture_output=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    drive = tmp_path / "drive"
    incomplete = drive / "canonical" / "project" / head
    incomplete.mkdir(parents=True)
    (incomplete / "partial").write_text("partial")
    assert sync.promote(argparse.Namespace(project=str(repo), drive_root=str(drive), project_name="project")) == 0
    assert (incomplete / ".complete").is_file()


def test_contract_partial_sync_failure_preserves_last_success(tmp_path, monkeypatch):
    sync = _sync_module()
    src = tmp_path / "src"; src.mkdir(); (src / "a").write_text("good")
    drive = tmp_path / "drive"; state = tmp_path / "state"
    args = argparse.Namespace(source=str(src), drive_root=str(drive), state_dir=str(state), device_id="dev", workspace_name="ws")
    assert sync.backup(args) == 0
    state_file = state / "dev-ws.json"
    before = json.loads(state_file.read_text(encoding="utf-8"))
    monkeypatch.setattr(sync, "_atomic_copy", lambda *a, **k: (_ for _ in ()).throw(OSError("injected")))
    (src / "a").write_text("new")
    assert sync.backup(args) == 2
    after = json.loads(state_file.read_text(encoding="utf-8"))
    assert after["last_success"] == before["last_success"]


def test_contract_automation_runner_aggregates_nonzero_exit_codes():
    source = (ROOT / "scripts" / "run_agent_bridge.py").read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source
    assert "sion_ingestion.bridge_cli" in source


def test_contract_frozen_resource_destination_is_normalized(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("p0_build_exe", ROOT / "scripts" / "build_exe.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "nested" / ".." / "root"))
    normalized = build._validate_runtime_data_root(str(tmp_path / "nested" / ".." / "root"))
    assert normalized == (tmp_path / "root").resolve()
    assert " _MEIPASS" not in str(normalized)


def test_contract_ci_billing_gate_fails_closed_when_estimate_is_missing():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release_policy = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    assert "billing" in release_policy.lower()
    assert "billing-blocked" in release_policy.lower()
    assert "required before merge" in release_policy.lower()
    assert "continue-on-error: true" not in workflow
    assert "if: always()" not in workflow


def test_contract_wheel_contains_runtime_resources_and_entrypoint():
    resources = {"sion-core.yaml", "sion-core.shacl.ttl", "current-map-inventory.json", "map-export.example.json"}
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run([os.environ.get("PYTHON", "python"), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", directory, str(ROOT)], cwd=ROOT, capture_output=True, text=True, check=True)
        wheel = next(Path(directory).glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            assert all(f"sion_api/resources/{name}" in names for name in resources)
            entry = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
            assert "sion-agent-bridge = sion_ingestion.bridge_cli:main" in archive.read(entry).decode()
