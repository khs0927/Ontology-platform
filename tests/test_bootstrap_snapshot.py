"""Read-only bootstrap snapshot manifests (issue #71 step B): create, verify, fail closed."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from sion_drive_store.bootstrap_snapshot import (
    SCHEMA,
    SnapshotError,
    _content_digest,
    create_manifest,
    main,
    verify_manifest,
    write_manifest,
)

CREATED_AT = "2026-11-05T00:00:00Z"

GRAPH = {
    "schema": "sion-map-export/v1",
    "source": "test",
    "expected_node_count": 2,
    "expected_edge_count": 1,
    "nodes": [
        {"stable_key": "t:a", "entity_type_id": "Concept", "name": "A", "ontology_version": "1.0"},
        {"stable_key": "t:b", "entity_type_id": "Workflow", "name": "B"},
    ],
    "edges": [
        {"stable_key": "t:a-b", "source_stable_key": "t:a", "target_stable_key": "t:b",
         "relation_type_id": "SUPPORTS"}
    ],
}


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE entities (id INTEGER PRIMARY KEY, stable_key TEXT);
        CREATE TABLE sion_schema_migrations (version TEXT PRIMARY KEY);
        INSERT INTO entities (stable_key) VALUES ('a'), ('b'), ('c');
        INSERT INTO sion_schema_migrations VALUES ('001_core'), ('002_vector');
        PRAGMA user_version = 7;
        """
    )
    conn.execute('CREATE TABLE "odd ""name""" (x INTEGER)')
    conn.commit()
    conn.close()


@pytest.fixture()
def export_root(tmp_path: Path) -> Path:
    root = tmp_path / "export"
    (root / "graph").mkdir(parents=True)
    (root / "db").mkdir()
    (root / "graph" / "sion-graph-latest.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    (root / "graph" / "sion-evidence-latest.jsonl").write_text('{"a":1}\n{"a":2}\n\n', encoding="utf-8")
    _make_db(root / "db" / "sion-latest.db")
    return root


def _snapshot_state(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_manifest_describes_export_and_db(export_root: Path) -> None:
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    assert manifest["schema"] == SCHEMA
    assert manifest["created_at"] == CREATED_AT
    by_uri = {item["source_uri"]: item for item in manifest["files"]}
    assert set(by_uri) == {
        "snapshot:db/sion-latest.db",
        "snapshot:graph/sion-evidence-latest.jsonl",
        "snapshot:graph/sion-graph-latest.json",
    }
    db = by_uri["snapshot:db/sion-latest.db"]
    assert db["kind"] == "sqlite"
    assert db["open_uri"] == "file:sion-latest.db?mode=ro&immutable=1"
    assert manifest["sources"] == ["."]
    assert db["row_counts"] == {"entities": 3, 'odd "name"': 0, "sion_schema_migrations": 2}
    assert db["schema"]["user_version"] == 7
    assert db["schema"]["migrations"] == {"sion_schema_migrations": ["001_core", "002_vector"]}
    assert len(db["schema"]["sqlite_master_sha256"]) == 64
    graph = by_uri["snapshot:graph/sion-graph-latest.json"]
    assert graph["kind"] == "map-export"
    assert graph["row_counts"] == {"nodes": 2, "edges": 1}
    assert graph["ontology_versions"] == ["1.0"]
    assert by_uri["snapshot:graph/sion-evidence-latest.jsonl"]["row_counts"] == {"records": 2}
    assert all(len(item["sha256"]) == 64 and item["size_bytes"] > 0 for item in manifest["files"])
    # no absolute paths anywhere in the manifest
    assert str(export_root) not in json.dumps(manifest)
    assert verify_manifest(manifest, export_root) == []


def test_snapshot_never_writes_to_the_source(export_root: Path) -> None:
    before = _snapshot_state(export_root)
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    assert verify_manifest(manifest, export_root) == []
    assert _snapshot_state(export_root) == before
    assert not list(export_root.rglob("*-wal")) and not list(export_root.rglob("*-journal"))
    assert not list(export_root.rglob("*-shm"))


def test_wal_mode_database_gets_no_sidecars(tmp_path: Path) -> None:
    # sqlite3 backup() of a WAL source keeps WAL mode, so snapshots can be WAL-mode databases
    root = tmp_path / "export"
    root.mkdir()
    db = root / "wal.db"
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode=wal").fetchone()[0] == "wal"
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1), (2)")
    conn.commit()
    conn.close()
    assert db.read_bytes()[18:20] == b"\x02\x02"
    for sidecar in ("-wal", "-shm"):
        db.with_name(db.name + sidecar).unlink(missing_ok=True)
    before = _snapshot_state(root)

    manifest = create_manifest(root, created_at=CREATED_AT)
    assert manifest["files"][0]["row_counts"] == {"t": 2}
    assert verify_manifest(manifest, root) == []
    assert _snapshot_state(root) == before
    assert sorted(p.name for p in root.iterdir()) == ["wal.db"]


def test_verify_reports_files_added_after_the_manifest(export_root: Path) -> None:
    manifest = create_manifest(export_root, ["graph"], created_at=CREATED_AT)
    assert manifest["sources"] == ["graph"]
    (export_root / "graph" / "late.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (export_root / "db" / "outside-the-sources.txt").write_text("x", encoding="utf-8")
    assert verify_manifest(manifest, export_root) == [
        "snapshot:graph/late.jsonl: not in the manifest (added after it was made)"
    ]


def test_verify_rejects_escaping_recorded_sources(export_root: Path) -> None:
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    manifest["sources"] = ["../elsewhere"]
    assert verify_manifest(manifest, export_root) == ["source '../elsewhere': path escapes the root"]


def test_manifest_is_reproducible(export_root: Path) -> None:
    first = create_manifest(export_root, created_at=CREATED_AT)
    second = create_manifest(export_root, created_at=CREATED_AT)
    assert first == second


def test_verify_fails_closed_on_changes(export_root: Path) -> None:
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    conn = sqlite3.connect(export_root / "db" / "sion-latest.db")
    conn.execute("INSERT INTO entities (stable_key) VALUES ('d')")
    conn.commit()
    conn.close()
    problems = verify_manifest(manifest, export_root)
    assert any("sion-latest.db: sha256 differs" in p for p in problems)
    assert any("row_counts differs" in p for p in problems)

    (export_root / "graph" / "sion-evidence-latest.jsonl").unlink()
    assert any("sion-evidence-latest.jsonl: missing" in p for p in verify_manifest(manifest, export_root))


def test_verify_detects_edited_manifest(export_root: Path) -> None:
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    manifest["files"][0]["sha256"] = "0" * 64
    problems = verify_manifest(manifest, export_root)
    assert any("content_sha256" in p for p in problems)
    assert any("sha256 differs" in p for p in problems)
    assert verify_manifest({"schema": "other"}, export_root)


def test_verify_rejects_paths_escaping_root(export_root: Path) -> None:
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    manifest["files"][0]["source_uri"] = "snapshot:../outside.db"
    manifest["content_sha256"] = _content_digest(manifest["files"])
    assert any("escapes the root" in p for p in verify_manifest(manifest, export_root))


@pytest.mark.parametrize("name", ["plan.dwg", "site.DXF", "model.skp", "model.skb"])
def test_cad_originals_refused_unless_hash_only(export_root: Path, name: str) -> None:
    cad = export_root / "cad" / name
    cad.parent.mkdir()
    cad.write_bytes(b"0\nSECTION\n")
    with pytest.raises(SnapshotError, match="CAD original"):
        create_manifest(export_root, created_at=CREATED_AT)
    manifest = create_manifest(export_root, created_at=CREATED_AT, allow_cad_hash_only=True)
    entry = next(item for item in manifest["files"] if item["source_uri"].endswith(name))
    assert entry["kind"] == "cad-original" and entry["hash_only"] is True
    assert set(entry) == {"source_uri", "sha256", "size_bytes", "kind", "hash_only"}
    assert verify_manifest(manifest, export_root) == []


def test_secrets_and_caches_are_excluded(export_root: Path) -> None:
    (export_root / ".env").write_text("SION_TOKEN=do-not-copy\n", encoding="utf-8")
    (export_root / "graph" / "client_secret_123.json").write_text("{}", encoding="utf-8")
    (export_root / "deploy.pem").write_text("-----BEGIN-----", encoding="utf-8")
    (export_root / ".git").mkdir()
    (export_root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    manifest = create_manifest(export_root, created_at=CREATED_AT)
    text = json.dumps(manifest)
    assert ".env" not in text and "client_secret" not in text and "deploy.pem" not in text
    assert manifest["excluded"] == {"secret": 3, "vcs-or-cache": 1}
    assert manifest["file_count"] == 3
    with pytest.raises(SnapshotError, match="secret"):
        create_manifest(export_root, [".env"], created_at=CREATED_AT)


def test_live_sqlite_is_refused(export_root: Path) -> None:
    (export_root / "db" / "sion-latest.db-wal").write_bytes(b"x" * 32)
    with pytest.raises(SnapshotError, match="live database"):
        create_manifest(export_root, created_at=CREATED_AT)
    with pytest.raises(SnapshotError, match="sidecar"):
        create_manifest(export_root, ["db/sion-latest.db-wal"], created_at=CREATED_AT)


def test_inconsistent_map_export_is_refused(export_root: Path) -> None:
    broken = dict(GRAPH, expected_edge_count=5)
    (export_root / "graph" / "sion-graph-latest.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(SnapshotError, match="expected_edge_count=5"):
        create_manifest(export_root, created_at=CREATED_AT)


def test_created_at_must_be_timezone_aware(export_root: Path) -> None:
    with pytest.raises(SnapshotError, match="timezone"):
        create_manifest(export_root, created_at="2026-11-05T00:00:00")
    with pytest.raises(SnapshotError, match="ISO-8601"):
        create_manifest(export_root, created_at="yesterday")


def test_sources_must_stay_inside_root(export_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(SnapshotError, match="inside --root"):
        create_manifest(export_root, [str(outside)], created_at=CREATED_AT)
    if hasattr(os, "symlink"):
        try:
            (export_root / "link.json").symlink_to(outside)
        except OSError:  # pragma: no cover - Windows without symlink privilege
            return
        manifest = create_manifest(export_root, created_at=CREATED_AT)
        assert manifest["excluded"] == {"symlink": 1}
        with pytest.raises(SnapshotError, match="symlink"):
            create_manifest(export_root, ["link.json"], created_at=CREATED_AT)


def test_manifest_never_written_into_source_or_over_existing(export_root: Path, tmp_path: Path) -> None:
    manifest = create_manifest(export_root, ["graph"], created_at=CREATED_AT)
    with pytest.raises(SnapshotError, match="inside a snapshot source"):
        write_manifest(manifest, export_root / "graph" / "m.json", root=export_root, sources=["graph"])
    out = write_manifest(manifest, tmp_path / "manifests" / "m.json", root=export_root, sources=["graph"])
    assert json.loads(out.read_text(encoding="utf-8")) == manifest
    with pytest.raises(SnapshotError, match="already exists"):
        write_manifest(manifest, out, root=export_root, sources=["graph"])


def test_cli_create_and_verify(export_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "manifest.json"
    assert main(["create", "--root", str(export_root), "--created-at", CREATED_AT, "--out", str(out)]) == 0
    assert main(["verify", str(out), "--root", str(export_root)]) == 0
    assert "OK 3 files verified" in capsys.readouterr().out

    (export_root / "graph" / "sion-graph-latest.json").write_text(json.dumps(dict(GRAPH, source="x")), encoding="utf-8")
    assert main(["verify", str(out), "--root", str(export_root)]) == 1
    assert "FAIL snapshot:graph/sion-graph-latest.json" in capsys.readouterr().err

    (export_root / "x.dwg").write_bytes(b"AC1032")
    assert main(["create", "--root", str(export_root), "--created-at", CREATED_AT]) == 2
    assert "CAD original" in capsys.readouterr().err
