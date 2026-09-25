from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from sion_ingestion.agent_bridge import AgentSession
from sion_ingestion.bridge_cli import _atomic_publish, _data_root, _publish_lock, _runtime_path, run_cycle
from sion_ingestion.dlp import DLPDecision


def _args(**overrides):
    values = {
        "export_out": "runtime/export.json",
        "pg_out": "runtime/export.sql",
        "graph_out": "runtime/export.md",
        "dry_run": False,
        "db_url": "sqlite://",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _wire(monkeypatch, tmp_path, drive=None, import_error=None):
    session = AgentSession("synthetic-123456789", "codex", "clean", device_id="dev", cwd=str(tmp_path))
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli.PROVIDER_REGISTRY",
        {"codex": lambda: SimpleNamespace(discover=lambda limit=None: [session])},
    )
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    monkeypatch.setattr("sion_ingestion.bridge_cli.detect_google_drive_root", lambda: drive)
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli.scan_payload",
        lambda payload, cwd=None: DLPDecision(True, "allowed", payload),
    )

    if import_error is None:
        class _Engine:
            def dispose(self):
                return None

        monkeypatch.setattr("sion_api.db.build_engine", lambda url: _Engine())
        monkeypatch.setattr(
            "sion_api.db.build_session_factory",
            lambda engine: (lambda: _NullSession()),
        )
        monkeypatch.setattr("sion_api.repository.seed_core_types", lambda session: None)
        monkeypatch.setattr(
            "sion_ingestion.bridge_cli.import_map_export",
            lambda session, export, already_scanned=None: SimpleNamespace(created_nodes=1, skipped_nodes=0),
        )
    else:
        def _boom(session, export, already_scanned=None):
            raise import_error

        monkeypatch.setattr("sion_ingestion.bridge_cli.import_map_export", _boom)
        monkeypatch.setattr("sion_api.db.build_engine", lambda url: _Engine())
        monkeypatch.setattr("sion_api.db.build_session_factory", lambda engine: (lambda: _NullSession()))
        monkeypatch.setattr("sion_api.repository.seed_core_types", lambda session: None)


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- publish primitive -------------------------------------------------


def test_atomic_publish_replaces_target_and_cleans_temp(tmp_path):
    src = tmp_path / "staged.txt"
    src.write_text("payload")
    dst = tmp_path / "out" / "final.txt"
    digest, size = hashlib.sha256(b"payload").hexdigest(), len(b"payload")
    _atomic_publish(src, dst, digest, size)
    assert dst.read_text() == "payload"
    assert not list((tmp_path / "out").glob("*.sion-publish.tmp"))
    assert not list((tmp_path / "out").glob("*.sion-publish.lock"))


def test_atomic_publish_rejects_digest_mismatch_without_touching_target(tmp_path):
    src = tmp_path / "staged.txt"
    src.write_text("payload")
    dst = tmp_path / "out.txt"
    dst.write_text("previous")
    with pytest.raises(OSError):
        _atomic_publish(src, dst, "0" * 64, 7)
    assert dst.read_text() == "previous"
    assert not list(tmp_path.glob("*.sion-publish.tmp"))


def test_publish_lock_rejects_concurrent_writer(tmp_path):
    lock = tmp_path / ".x.lock"
    with _publish_lock(lock):
        assert json.loads(lock.read_text())["pid"] > 0
        with pytest.raises(RuntimeError):
            with _publish_lock(lock):
                pass
    assert not lock.exists()


# --- staging before publish -------------------------------------------


def test_cycle_publishes_only_after_db_import_and_keeps_data_root_containment(tmp_path, monkeypatch):
    root = tmp_path / "data"
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setenv("SION_DATA_ROOT", str(root))
    _wire(monkeypatch, tmp_path, drive=drive)

    assert run_cycle(_args(), ["codex"], None) == 0

    for rel in ("runtime/export.json", "runtime/export.sql", "runtime/export.md"):
        published = _runtime_path(rel, _data_root())
        assert published.is_file()
        assert published.is_relative_to(root)
    # staging is fully reclaimed after a successful cycle
    assert not list((root / "staging").glob("*")) if (root / "staging").exists() else True

    for rel in (
        "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_pg_knowledge_graph.sql",
        "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_knowledge_graph.json",
        "AEC-INTELLIGENCE/09_AGENT_MEMORY/agent_knowledge_graph.md",
    ):
        assert (drive / rel).is_file()
    assert not list(drive.rglob("*.sion-publish.tmp"))
    assert not list(drive.rglob("*.sion-publish.lock"))


def test_db_import_failure_publishes_nothing_and_exits_nonzero(tmp_path, monkeypatch):
    root = tmp_path / "data"
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setenv("SION_DATA_ROOT", str(root))
    _wire(monkeypatch, tmp_path, drive=drive, import_error=RuntimeError("db down"))

    assert run_cycle(_args(), ["codex"], None) == 1
    assert not list(drive.rglob("*.sql"))
    assert not list(drive.rglob("*.json"))
    assert not list(drive.rglob("*.md"))
    assert not _runtime_path("runtime/export.json", root).exists()
    assert not _runtime_path("runtime/export.sql", root).exists()
    assert not _runtime_path("runtime/export.md", root).exists()


def test_dry_run_creates_no_staging_sink_or_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _wire(monkeypatch, tmp_path, drive=None)
    assert run_cycle(_args(dry_run=True), ["codex"], None) == 0
    assert list(tmp_path.iterdir()) == []


# --- Drive partial failure --------------------------------------------


def test_drive_partial_failure_returns_nonzero_and_reports_last_attempt(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setenv("SION_DATA_ROOT", str(root))
    _wire(monkeypatch, tmp_path, drive=drive)

    real = _atomic_publish
    calls = {"n": 0}

    def flaky(src, dst, digest, size):
        if dst.parent.name == "03_KNOWLEDGE_GRAPH" and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("injected drive failure")
        return real(src, dst, digest, size)

    monkeypatch.setattr("sion_ingestion.bridge_cli._atomic_publish", flaky)
    assert run_cycle(_args(), ["codex"], None) == 1
    out = capsys.readouterr().out
    assert "partial_failure" in out
    assert "last_attempt=" in out
    # local sinks still published; staging reclaimed; no temp/lock residue on Drive
    assert _runtime_path("runtime/export.json", root).is_file()
    assert not list(drive.rglob("*.sion-publish.tmp"))
    assert not list(drive.rglob("*.sion-publish.lock"))


def test_drive_publish_verifies_hash_by_reading_written_file_back(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _wire(monkeypatch, tmp_path, drive=drive)
    assert run_cycle(_args(), ["codex"], None) == 0
    staged_hash = _sha(_runtime_path("runtime/export.json", _data_root()))
    drive_hash = _sha(drive / "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_knowledge_graph.json")
    assert staged_hash == drive_hash
