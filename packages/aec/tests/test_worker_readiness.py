"""Source mount and RAM gates: no PostgreSQL, CAD conversion, or live infrastructure."""

import os
from types import SimpleNamespace

import pytest

from aec_intelligence.operational import census, worker
from aec_intelligence.operational.config import Settings
from aec_intelligence.operational.db import Database


class FakeDB:
    def __init__(self):
        self.claims = 0
        self.finished = []
        self.deferred = []

    def claim(self, **kwargs):
        self.claims += 1
        return {"id": "job-1", "payload": {}}

    def heartbeat(self, *args):
        return True

    def finish(self, *args, **kwargs):
        self.finished.append(args)
        return True

    def defer_unavailable_source(self, *args):
        self.deferred.append(args)
        return True


def test_no_claim_when_root_missing_then_resumes(tmp_path, monkeypatch):
    root = tmp_path / "mounted"
    settings = Settings("unused", tmp_path, (root,))
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")
    monkeypatch.setattr(ingest, "process_job", lambda job: {"status": "SUCCESS"})
    with pytest.raises(worker.SourceUnavailableError):
        ingest.run_once()
    assert db.claims == 0
    root.mkdir()
    assert ingest.run_once() is True
    assert db.claims == 1
    assert len(db.finished) == 1


def test_mount_loss_after_claim_defers_without_failed_finish(tmp_path, monkeypatch):
    settings = Settings("unused", tmp_path, (tmp_path,))
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")

    def unavailable(job):
        raise worker.SourceUnavailableError("mount disconnected")

    monkeypatch.setattr(ingest, "process_job", unavailable)
    assert ingest.run_once() is False
    assert db.deferred == [("job-1", "test")]
    assert db.finished == []


def test_linux_container_ignores_host_only_windows_roots(monkeypatch):
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="posix"))
    assert worker.unavailable_import_roots(SimpleNamespace(import_roots=(r"G:\missing",))) == []


@pytest.mark.parametrize("available,threshold,paused", [(1024, "2048", True), (4096, "2048", False),
                                                       (None, "2048", True), (4096, "invalid", True),
                                                       (4096, "0", True)])
def test_memory_gate_fails_closed(monkeypatch, available, threshold, paused):
    monkeypatch.setenv("AEC_MIN_AVAILABLE_MB", threshold)
    monkeypatch.setattr(census, "os", SimpleNamespace(name="nt", getenv=os.getenv))
    monkeypatch.setattr(census, "_host_available_memory_mb", lambda: available)
    assert bool(census.worker_memory_pause_reason()) is paused


def test_paused_loop_resumes_and_still_observes_stop(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_root=tmp_path, dsn="unused")
    stop = iter([None, None, "stop file present"])
    memory = iter(["low memory", None])
    claims = []

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            pass

        def run_once(self):
            claims.append(1)
            return True

    monkeypatch.setattr(worker, "IngestionWorker", FakeWorker)
    monkeypatch.setattr(census, "worker_stop_reason", lambda settings: next(stop))
    monkeypatch.setattr(census, "worker_memory_pause_reason", lambda: next(memory))
    monkeypatch.setattr(census.time, "sleep", lambda seconds: None)
    assert census.worker_process(settings, "cad", 0.01, 0) == 1
    assert claims == [1]


def test_deferral_is_lease_owner_guarded_and_refunds_attempt(monkeypatch):
    statements = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            statements.append((query, params))
            return SimpleNamespace(rowcount=1)

    db = Database("unused")
    monkeypatch.setattr(db, "connect", lambda: FakeConn())
    assert db.defer_unavailable_source("job", "owner")
    query, params = statements[0]
    assert "attempts=GREATEST(attempts-1,0)" in query
    assert "lease_owner=%s AND state='RUNNING' AND lease_until>now()" in query
    assert params == ("job", "owner")


def test_run_forever_pauses_on_missing_root_instead_of_crashing(tmp_path, monkeypatch):
    root = tmp_path / "unmounted"
    settings = Settings("unused", tmp_path, (root,))
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")
    waits = []

    def fake_wait(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            root.mkdir()
        return False

    def process_then_stop(job):
        ingest.stop()
        return {"status": "SUCCESS"}

    monkeypatch.setattr(ingest._stop_event, "wait", fake_wait)
    monkeypatch.setattr(ingest, "process_job", process_then_stop)
    ingest.run_forever(poll_interval=0.01)
    assert waits == [1.0, 1.0]
    assert db.claims == 1
    assert len(db.finished) == 1


@pytest.mark.parametrize("error", [FileNotFoundError("vanished while hashing"), OSError(5, "I/O error"),
                                   ValueError("DXF structure error")])
def test_mount_loss_during_parsing_defers_instead_of_failing(tmp_path, monkeypatch, error):
    root = tmp_path / "mounted"
    root.mkdir()
    settings = Settings("unused", tmp_path, (root,))
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")

    def disconnect_mid_job(job):
        root.rmdir()  # the share drops after claim and the initial is_file() check
        raise error

    monkeypatch.setattr(ingest, "process_job", disconnect_mid_job)
    assert ingest.run_once() is False
    assert db.deferred == [("job-1", "test")]
    assert db.finished == []


def test_parse_error_with_roots_mounted_still_fails_the_job(tmp_path, monkeypatch):
    root = tmp_path / "mounted"
    root.mkdir()
    settings = Settings("unused", tmp_path, (root,))
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")

    def broken(job):
        raise ValueError("corrupt drawing")

    monkeypatch.setattr(ingest, "process_job", broken)
    assert ingest.run_once() is True
    assert db.deferred == []
    assert len(db.finished) == 1


def test_root_probe_failure_after_error_defers(tmp_path, monkeypatch):
    settings = Settings("unused", tmp_path, ())
    db = FakeDB()
    ingest = worker.IngestionWorker(db, settings, worker_id="test")
    monkeypatch.setattr(ingest, "process_job", lambda job: (_ for _ in ()).throw(OSError("parse")))
    calls = iter([[], RuntimeError("probe broke")])

    def probe(settings):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(worker, "unavailable_import_roots", probe)
    assert ingest.run_once() is False
    assert db.deferred == [("job-1", "test")]
    assert db.finished == []
