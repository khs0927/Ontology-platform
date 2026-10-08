"""Storage root on Google Drive: layout, export-on-write of the live DB, asset placement."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.drive_export import (
    PROJECT_DIR,
    DriveExporter,
    StorageLayout,
    export_snapshot,
    install_export_on_write,
    publish_assets,
)
from sion_api.main import create_app
from sion_api.repository import seed_core_types
from sion_ingestion.map_import import MapExport, import_map_export

GRAPH = {
    "schema": "sion-map-export/v1",
    "source": "test",
    "nodes": [
        {"stable_key": "t:a", "entity_type_id": "Concept", "name": "A", "properties": {"ko": "가"}},
        {"stable_key": "t:b", "entity_type_id": "Workflow", "name": "B"},
    ],
    "edges": [
        {
            "stable_key": "t:a-b",
            "source_stable_key": "t:a",
            "target_stable_key": "t:b",
            "relation_type_id": "SUPPORTS",
            "confidence": 0.5,
        }
    ],
}


def _db(tmp_path: Path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'live' / 'sion.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        seed_core_types(session)
        import_map_export(session, MapExport.model_validate(GRAPH))
    return engine, factory


def test_layout_from_env(tmp_path):
    assert StorageLayout.from_env({}) is None
    drive = StorageLayout.from_env({"SION_DRIVE_ROOT": str(tmp_path)})
    assert drive.root == tmp_path / PROJECT_DIR
    assert drive.snapshots_db == tmp_path / PROJECT_DIR / "01_SNAPSHOTS" / "db"
    explicit = StorageLayout.from_env({"SION_STORAGE_ROOT": str(tmp_path / "x"), "SION_DRIVE_ROOT": str(tmp_path)})
    assert explicit.root == tmp_path / "x"
    assert DriveExporter.from_env(None, {"SION_DRIVE_ROOT": str(tmp_path), "SION_DRIVE_EXPORT_ON_WRITE": "0"}) is None


def test_export_snapshot_is_consistent_and_reimportable(tmp_path):
    engine, _ = _db(tmp_path)
    layout = StorageLayout(tmp_path / "drive")
    result = export_snapshot(engine, layout, reason="test", keep=2)
    assert result["counts"] == {"entities": 2, "relations": 1, "evidence": 0}
    graph = json.loads((layout.exports_graph / "sion-graph-latest.json").read_text(encoding="utf-8"))
    assert MapExport.model_validate(graph).nodes[0].properties == {"ko": "가"}
    snap = sqlite3.connect(layout.snapshots_db / "sion-latest.db")
    assert snap.execute("select count(*) from entities").fetchone()[0] == 2
    snap.close()
    assert "CREATE TABLE" in (layout.snapshots_db / "sion-latest.sql").read_text(encoding="utf-8")
    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    assert manifest["schema"] == "sion-storage-manifest/v1" and manifest["last_export"]["reason"] == "test"
    assert set(manifest["last_export"]["files"]) >= {
        "02_EXPORTS/graph/sion-graph-latest.json",
        "01_SNAPSHOTS/db/sion-latest.db",
    }
    # the live database is never written to the storage root
    assert not list(layout.root.rglob("sion.db"))


def test_snapshot_retention_only_touches_own_files(tmp_path):
    engine, _ = _db(tmp_path)
    layout = StorageLayout(tmp_path / "drive")
    layout.ensure()
    keepme = layout.snapshots_db / "notes.txt"
    keepme.write_text("user file", encoding="utf-8")
    for day in (1, 2, 3):
        export_snapshot(engine, layout, keep=2, now=datetime(2026, 10, day, tzinfo=timezone.utc))
    stamped = sorted(p.name for p in layout.snapshots_db.glob("sion-2026*.db"))
    assert stamped == ["sion-20261002T000000Z.db", "sion-20261003T000000Z.db"]
    assert keepme.exists()


def test_commit_schedules_one_debounced_export(tmp_path):
    engine, factory = _db(tmp_path)
    exporter = DriveExporter(engine, StorageLayout(tmp_path / "drive"), debounce_s=3600)
    install_export_on_write(factory, exporter)
    with factory() as session:
        session.commit()  # nothing written: no export
    assert exporter.status()["pending"] is False
    with factory() as session:
        import_map_export(
            session,
            MapExport.model_validate(
                {**GRAPH, "nodes": [{"stable_key": "t:c", "entity_type_id": "Concept", "name": "C"}], "edges": []}
            ),
        )
    assert exporter.status()["pending"] is True
    exporter.flush()
    assert exporter.last_result["counts"]["entities"] == 3 and exporter.last_result["reason"] == "commit"


def test_api_exports_on_write_and_reports_status(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_STORAGE_ROOT", str(tmp_path / "drive"))
    monkeypatch.setenv("SION_DRIVE_EXPORT_DEBOUNCE_S", "3600")
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/storage/status").json()["status"] == "ok"
        created = client.post(
            "/api/v1/entities", json={"stable_key": "api:x", "entity_type_id": "Concept", "name": "X"}
        )
        assert created.status_code == 201
        assert client.get("/api/v1/storage/status").json()["pending"] is True
        forced = client.post("/api/v1/storage/export").json()
        assert forced["counts"]["entities"] == 1
    graph = json.loads((tmp_path / "drive" / "02_EXPORTS" / "graph" / "sion-graph-latest.json").read_text("utf-8"))
    assert [n["stable_key"] for n in graph["nodes"]] == ["api:x"]


def test_storage_disabled_without_root(monkeypatch):
    for key in ("SION_STORAGE_ROOT", "SION_DRIVE_ROOT", "GOOGLE_DRIVE_ROOT"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True), base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/storage/status").json()["status"] == "disabled"
        assert client.post("/api/v1/storage/export").status_code == 503


def test_publish_assets_is_idempotent_and_never_deletes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data/sources/sketchup/m").mkdir(parents=True)
    (repo / "data/sources/sketchup/m/dump.json").write_text("{}", encoding="utf-8")
    (repo / "data/bootstrap").mkdir(parents=True)
    (repo / "data/bootstrap/pack.json").write_text("[]", encoding="utf-8")
    (repo / "docs/sketchup").mkdir(parents=True)
    (repo / "docs/sketchup/GUIDE.ko.md").write_text("# 지침", encoding="utf-8")
    (repo / "scripts/sketchup").mkdir(parents=True)
    (repo / "scripts/sketchup/dump_model.rb").write_text("# ruby", encoding="utf-8")
    layout = StorageLayout(tmp_path / "drive")
    extra = layout.sources / "sketchup" / "m" / "render.png"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"png")
    first = publish_assets(layout, repo)
    assert sorted(first["placed"]) == [
        "00_SOURCES/sketchup/m/dump.json",
        "00_SOURCES/sketchup/scripts/dump_model.rb",
        "02_EXPORTS/bootstrap/pack.json",
        "03_DOCS/sketchup/GUIDE.ko.md",
    ]
    second = publish_assets(layout, repo)
    assert second["placed"] == [] and len(second["unchanged"]) == 4
    assert extra.exists()


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_export_on_write_can_be_disabled(tmp_path, value):
    assert (
        DriveExporter.from_env(None, {"SION_STORAGE_ROOT": str(tmp_path), "SION_DRIVE_EXPORT_ON_WRITE": value}) is None
    )


def test_local_embeddings_endpoint_speaks_openai_format():
    import array
    import base64
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "local_embeddings", Path(__file__).resolve().parents[1] / "scripts" / "local_embeddings.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Fake:
        def embed(self, texts):
            return [[float(len(t))] * 3 for t in texts]

    client = TestClient(module.create_app("fake", embedder=Fake()))
    plain = client.post("/v1/embeddings", json={"input": ["ab", "그룹화"], "model": "fake"}).json()
    assert [d["embedding"] for d in plain["data"]] == [[2.0, 2.0, 2.0], [3.0, 3.0, 3.0]]
    packed = client.post("/v1/embeddings", json={"input": "ab", "encoding_format": "base64"}).json()
    decoded = array.array("f")
    decoded.frombytes(base64.b64decode(packed["data"][0]["embedding"]))
    assert decoded.tolist() == [2.0, 2.0, 2.0]
    assert client.post("/v1/embeddings", json={"input": "ab", "dimensions": 5}).status_code == 422
