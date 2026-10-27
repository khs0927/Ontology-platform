"""backup: in-container pg_dump + docker cp, local-first dump with a Drive mirror that may be offline."""

import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aec_intelligence.operational import backup

DSN = "postgresql://aec@127.0.0.1:55432/aec"
NOW = datetime(2026, 10, 9, 3, 0, 0, tzinfo=timezone.utc)


def _fake_docker(monkeypatch, *, dump_rc=0, cp_rc=0, payload=b"PGDMP-archive"):
    calls = []

    def run(cmd, stdout=None, stderr=None):
        calls.append(list(cmd))
        if cmd[1] == "exec" and "pg_dump" in cmd:
            return types.SimpleNamespace(returncode=dump_rc, stderr=b"dump boom")
        if cmd[1] == "cp":
            if cp_rc == 0:
                Path(cmd[3]).write_bytes(payload)
            return types.SimpleNamespace(returncode=cp_rc, stderr=b"cp boom")
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(backup.subprocess, "run", run)
    return calls


def test_docker_dump_writes_inside_container_then_copies_out(tmp_path, monkeypatch):
    calls = _fake_docker(monkeypatch)
    result = backup.run_backup(DSN, tmp_path / "local", docker_container="aec-db", now=NOW)
    final = Path(result["backup"])
    assert final.read_bytes().startswith(b"PGDMP") and final.name == "aec-db-20261009T030000Z.dump"
    dump, cp, rm = calls
    assert dump[:4] == ["docker", "exec", "aec-db", "pg_dump"] and "-f" in dump
    inner = dump[dump.index("-f") + 1]
    assert inner.startswith("/tmp/") and cp == ["docker", "cp", f"aec-db:{inner}", str(final) + ".partial"]
    assert rm == ["docker", "exec", "aec-db", "rm", "-f", inner]
    assert not list((tmp_path / "local").glob("*.partial"))
    assert "mirror" not in result


@pytest.mark.parametrize("kw", [{"dump_rc": 1}, {"cp_rc": 1}, {"payload": b"garbage"}])
def test_docker_dump_failure_leaves_no_partial_and_cleans_container(tmp_path, monkeypatch, kw):
    calls = _fake_docker(monkeypatch, **kw)
    with pytest.raises(RuntimeError):
        backup.run_backup(DSN, tmp_path / "local", docker_container="aec-db", now=NOW)
    assert list((tmp_path / "local").iterdir()) == []
    assert calls[-1][:5] == ["docker", "exec", "aec-db", "rm", "-f"]


def test_mirror_copies_and_rotates(tmp_path, monkeypatch):
    _fake_docker(monkeypatch)
    mirror = tmp_path / "drive"
    mirror.mkdir()
    old = backup.backup_name(now=NOW - timedelta(days=3))
    (mirror / old).write_bytes(b"PGDMP-old")
    (mirror / "unrelated.txt").write_text("x")
    result = backup.run_backup(DSN, tmp_path / "local", keep=1, docker_container="aec-db",
                               now=NOW, mirror=mirror)
    m = result["mirror"]
    assert m["status"] == "ok"
    assert [Path(p).name for p in m["copied"]] == ["aec-db-20261009T030000Z.dump"]
    assert [Path(p).name for p in m["deleted"]] == [old]
    assert sorted(p.name for p in mirror.iterdir()) == ["aec-db-20261009T030000Z.dump", "unrelated.txt"]


def test_mirror_offline_is_pending_and_retried_next_run(tmp_path, monkeypatch):
    _fake_docker(monkeypatch)
    mirror = tmp_path / "drive"  # not mounted yet
    first = backup.run_backup(DSN, tmp_path / "local", docker_container="aec-db", now=NOW, mirror=mirror)
    assert first["mirror"]["status"] == "pending"
    assert Path(first["backup"]).is_file()  # local dump kept even though Drive is offline
    mirror.mkdir()  # Drive comes back
    second = backup.run_backup(DSN, tmp_path / "local", docker_container="aec-db",
                               now=NOW + timedelta(hours=1), mirror=mirror)
    assert second["mirror"]["status"] == "ok"
    assert sorted(Path(p).name for p in second["mirror"]["copied"]) == [
        "aec-db-20261009T030000Z.dump", "aec-db-20261009T040000Z.dump"]


def test_mirror_oserror_mid_copy_is_pending(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    (local / backup.backup_name(now=NOW)).write_bytes(b"PGDMP")
    mirror = tmp_path / "drive"
    mirror.mkdir()

    def boom(src, dst):
        Path(dst).write_bytes(b"PG")
        raise OSError("drive went away")

    monkeypatch.setattr(backup.shutil, "copyfile", boom)
    result = backup.sync_mirror(local, mirror)
    assert result["status"] == "pending" and "drive went away" in result["reason"]
    assert list(mirror.iterdir()) == []  # no half-written .partial left behind


def test_local_pg_dump_path_unchanged(tmp_path, monkeypatch):
    def run(cmd, stdout=None, stderr=None):
        assert cmd[0] == "/x/pg_dump" and "--dbname" in cmd
        stdout.write(b"PGDMP")
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(backup.subprocess, "run", run)
    result = backup.run_backup(DSN, tmp_path, pg_dump="/x/pg_dump", now=NOW)
    assert Path(result["backup"]).read_bytes() == b"PGDMP"

