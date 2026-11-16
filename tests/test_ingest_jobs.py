"""Durable ingestion jobs (sion_ingestion.jobs on DBOS): queue, steps, idempotency, checkpoints, API."""

from __future__ import annotations

import os
import sqlite3

import pytest

pytest.importorskip("dbos")

from fastapi.testclient import TestClient  # noqa: E402
from sion_api import models  # noqa: E402
from sion_api.main import create_app  # noqa: E402
from sion_ingestion import jobs  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

NOTE = "# 펌프실 개요\n급수 펌프 2대\n## Valve schedule\nV-1 gate valve\n"


@pytest.fixture
def app_with_jobs(tmp_path, monkeypatch):
    # SION_TEST_JOBS_POSTGRES_URL runs the same tests with PostgreSQL as app and DBOS system database
    pg = os.getenv("SION_TEST_JOBS_POSTGRES_URL")
    if pg:
        from sqlalchemy import create_engine, text

        with create_engine(pg).begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public; DROP SCHEMA IF EXISTS dbos CASCADE"))
    elif sqlite3.sqlite_version_info < jobs.MIN_SQLITE:
        pytest.skip(f"SQLite {sqlite3.sqlite_version} is too old for DBOS; set SION_TEST_JOBS_POSTGRES_URL")
    monkeypatch.setenv("SION_JOBS_DATABASE_URL", pg or f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    app = create_app(database_url=pg or f"sqlite:///{tmp_path / 'sion.sqlite'}", auto_create_schema=True,
                     ingest_roots=[tmp_path], jobs=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        yield app, client
    jobs.stop()


def _write(tmp_path, name="pump.md", text=NOTE):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _count(app, model) -> int:
    with app.state.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_jobs_run_parse_load_relations_and_are_idempotent(app_with_jobs, tmp_path):
    app, c = app_with_jobs
    a, b = _write(tmp_path), _write(tmp_path, "empty.md", "   ")
    r = c.post("/api/v1/jobs/ingest", json={"paths": [str(a), str(b)]})
    assert r.status_code == 202, r.text
    queued = r.json()["jobs"]
    assert [j["path"] for j in queued] == [str(a), str(b)]

    done = jobs.wait(queued[0]["job_id"])
    assert done["status"] == "SUCCESS"
    result = done["result"]
    assert result["status"] == "ingested" and result["extractor"] == "text"
    assert result["load"]["created_nodes"] == 3 and result["load"]["evidence_created"] == 2
    assert "relations" in result and result["verification_state"] == "unverified"
    assert [s["step"] for s in done["steps"]] == ["parse", "load", "relations"] and all(s["done"] for s in done["steps"])

    skipped = jobs.wait(queued[1]["job_id"])["result"]
    assert skipped["status"] == "skipped" and skipped["reason"] == "no extractable text"

    nodes, evidence = _count(app, models.Entity), _count(app, models.Evidence)
    again = c.post("/api/v1/jobs/ingest", json={"paths": [str(a)]}).json()["jobs"][0]["job_id"]
    assert jobs.wait(again)["result"]["load"]["created_nodes"] == 0
    assert (_count(app, models.Entity), _count(app, models.Evidence)) == (nodes, evidence)

    listed = c.get("/api/v1/jobs").json()["jobs"]
    assert {j["job_id"] for j in listed} >= {queued[0]["job_id"], queued[1]["job_id"], again}
    assert c.get(f"/api/v1/jobs/{again}").json()["status"] == "SUCCESS"
    assert c.get("/api/v1/jobs/does-not-exist").status_code == 404


def test_finished_steps_are_checkpointed_not_rerun(app_with_jobs, tmp_path, monkeypatch):
    from dbos import DBOS
    from sion_ingestion import document_ingest

    app, c = app_with_jobs
    path = _write(tmp_path)
    calls = []
    real = document_ingest.extract_text
    monkeypatch.setattr(document_ingest, "extract_text", lambda p: calls.append(p) or real(p))
    job = c.post("/api/v1/jobs/ingest", json={"paths": [str(path)], "extract_relations": False}).json()["jobs"][0]["job_id"]
    first = jobs.wait(job)
    assert first["status"] == "SUCCESS" and len(calls) == 1
    # replay from step 2 (load): the recorded parse output is reused, the parser is not called again
    fork = DBOS.fork_workflow(job, 2)
    assert fork.get_result()["load"]["created_nodes"] == 0
    assert len(calls) == 1


def test_unreadable_file_is_a_skip_not_a_retry(app_with_jobs, tmp_path):
    _, c = app_with_jobs
    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"not a zip")
    job = c.post("/api/v1/jobs/ingest", json={"paths": [str(bad)]}).json()["jobs"][0]["job_id"]
    done = jobs.wait(job)
    assert done["status"] == "SUCCESS" and [s["step"] for s in done["steps"]] == ["parse"]
    assert done["result"]["status"] == "skipped" and "DOCX could not be read" in done["result"]["reason"]


def test_a_failing_step_marks_the_job_failed_and_retry_reuses_finished_steps(app_with_jobs, tmp_path, monkeypatch):
    from sion_ingestion import map_import

    _, c = app_with_jobs
    path = _write(tmp_path)
    real = map_import.import_map_export
    monkeypatch.setattr(map_import, "import_map_export", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    job = c.post("/api/v1/jobs/ingest", json={"paths": [str(path)], "extract_relations": False}).json()["jobs"][0]["job_id"]
    failed = jobs.wait(job)
    assert failed["status"] == "ERROR" and "db down" in failed["error"]
    assert [(st["step"], st["error"] is not None) for st in failed["steps"]] == [("parse", False), ("load", True)]
    monkeypatch.setattr(map_import, "import_map_export", real)
    from sion_ingestion import document_ingest

    monkeypatch.setattr(document_ingest, "extract_text", lambda p: (_ for _ in ()).throw(AssertionError("re-parsed")))
    retried = c.post(f"/api/v1/jobs/{job}/retry")
    assert retried.status_code == 202 and retried.json()["retry_of"] == job
    final = jobs.wait(retried.json()["job_id"])
    assert final["status"] == "SUCCESS" and final["result"]["load"]["created_nodes"] == 3  # parse output reused


def test_paths_are_confined_and_jobs_off_is_503(app_with_jobs, tmp_path):
    _, c = app_with_jobs
    assert c.post("/api/v1/jobs/ingest", json={"paths": ["/etc/hostname"]}).status_code == 403
    off = create_app(database_url="sqlite://", auto_create_schema=True, jobs=False)
    with TestClient(off, base_url="http://localhost", client=("127.0.0.1", 50000)) as c2:
        r = c2.post("/api/v1/jobs/ingest", json={"paths": [str(tmp_path / "x.md")]})
        assert r.status_code == 503 and "SION_JOBS=on" in r.json()["detail"]


def test_system_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("SION_JOBS_DATABASE_URL", raising=False)
    assert jobs.system_database_url("postgresql+psycopg://u@db/sion") == "postgresql+psycopg://u@db/sion"
    monkeypatch.setenv("SION_RUNTIME_DIR", str(tmp_path))
    assert jobs.system_database_url("sqlite:///x.db") == f"sqlite:///{(tmp_path / 'sion-jobs.sqlite').as_posix()}"
    monkeypatch.setenv("SION_JOBS_DATABASE_URL", "sqlite:///elsewhere.sqlite")
    assert jobs.system_database_url("postgresql://x") == "sqlite:///elsewhere.sqlite"


def test_old_sqlite_is_refused_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(jobs.sqlite3, "sqlite_version_info", (3, 37, 2))
    with pytest.raises(RuntimeError, match="SION_JOBS_DATABASE_URL to a PostgreSQL URL"):
        jobs.check_system_database("sqlite:///x.sqlite")
    jobs.check_system_database("postgresql+psycopg://u@db/sion")  # Postgres is unaffected
