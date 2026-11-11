"""Opt-in read-only API (AEC_API_READ_ONLY). The default path needs no PostgreSQL.

The session test at the bottom runs only when AEC_TEST_DATABASE_URL points at a disposable
database. It checks that the mobile flag makes the next transaction read-only, and that
leaving the flag unset still allows a write.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aec_intelligence.operational import api as api_module
from aec_intelligence.operational import readonly
from aec_intelligence.operational.config import Settings
from aec_intelligence.operational.db import Database

TOKEN = "correct-horse-battery-staple"
READER_DSN = "postgresql://aec_reader:not-a-placeholder@203.0.113.10:5432/aec"
ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "mobile-readonly"
PC_COMPOSE = ROOT / "docker-compose.yml"
OPS = ROOT / "scripts" / "ops"

AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeDatabase:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connect(self, statement_timeout_seconds=None):
        raise RuntimeError("db reached")
        yield


def _settings(tmp_path: Path, dsn: str = READER_DSN) -> Settings:
    return Settings(dsn=dsn, data_root=tmp_path / "data", import_roots=(tmp_path.resolve(),))


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, read_only: bool, token: str | None = TOKEN,
            dsn: str = READER_DSN) -> TestClient:
    monkeypatch.setattr(api_module, "Database", FakeDatabase)
    if read_only:
        monkeypatch.setenv("AEC_API_READ_ONLY", "1")
    else:
        monkeypatch.delenv("AEC_API_READ_ONLY", raising=False)
    if token is None:
        monkeypatch.delenv("AEC_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("AEC_API_TOKEN", token)
    monkeypatch.delenv("AEC_CORS_ORIGINS", raising=False)
    return TestClient(
        api_module.create_app(_settings(tmp_path, dsn)),
        raise_server_exceptions=False,
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    )


def test_pc_path_health_and_writes_stay_unchanged(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, read_only=False, token=None, dsn="dummy")
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "read_only" not in body and "canonical" not in body
    assert "x-aec-read-only" not in client.get("/healthz").headers
    # Validation still runs. A read-only deployment would have answered 405 first.
    res = client.post("/v1/ingestions", json={"path": "x", "queue": "nope"})
    assert res.status_code == 422


def test_read_only_refuses_to_start_without_a_real_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AEC_API_READ_ONLY", "1")
    monkeypatch.delenv("AEC_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="AEC_API_TOKEN"):
        api_module.create_app(_settings(tmp_path))
    monkeypatch.setenv("AEC_API_TOKEN", "replace-with-token")
    with pytest.raises(RuntimeError, match="placeholder"):
        api_module.create_app(_settings(tmp_path))


@pytest.mark.parametrize("dsn", [
    "postgresql://aec:not-a-placeholder@203.0.113.10:5432/aec",
    "postgresql://aec_reader:change-me@203.0.113.10:5432/aec",
    "postgresql://aec_reader:replace-with-password@203.0.113.10:5432/aec",
    "postgresql://aec_reader:not-a-placeholder@127.0.0.1:55432/aec",
    "postgresql://aec_reader:not-a-placeholder@localhost:55432/aec",
    "postgresql://aec_reader:not-a-placeholder@[::1]:55432/aec",
    "postgresql://aec_reader:not-a-placeholder@db:5432/aec",
    "postgresql://aec_reader:not-a-placeholder@aec-db:5432/aec",
    "host=127.0.0.1 port=55432 user=aec_reader password=not-a-placeholder",
    "",
])
def test_read_only_refuses_pc_and_placeholder_databases(tmp_path, monkeypatch, dsn):
    monkeypatch.setenv("AEC_API_READ_ONLY", "1")
    monkeypatch.setenv("AEC_API_TOKEN", TOKEN)
    with pytest.raises(RuntimeError) as caught:
        api_module.create_app(_settings(tmp_path, dsn))
    message = str(caught.value)
    if dsn:
        assert dsn not in message
    assert TOKEN not in message
    assert "not-a-placeholder" not in message


def test_read_only_allows_the_copy_address(tmp_path, monkeypatch):
    client = _client(
        tmp_path, monkeypatch, read_only=True,
        dsn="postgresql://aec_reader:not-a-placeholder@db-copy:5432/aec",
    )
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["read_only"] is True
    assert res.json()["canonical"] is False
    assert res.headers["x-aec-read-only"] == "1"
    assert res.headers["x-aec-canonical"] == "0"


def test_read_only_rejects_writes_before_the_database(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, read_only=True)
    for method, path, body in (
        ("POST", "/v1/ingestions", {"path": "x"}),
        ("POST", "/v1/jobs/00000000-0000-0000-0000-000000000000/retry", None),
        ("POST", "/v1/reviews", {"object_id": "o", "action": "CONFIRM"}),
        ("PUT", "/v1/search", {"query": "wall"}),
        ("DELETE", "/v1/objects/x", None),
    ):
        res = client.request(method, path, headers=AUTH, json=body)
        assert res.status_code == 405, (method, path, res.status_code)
        assert res.json() == {"detail": "This deployment is read-only", "read_only": True, "canonical": False}
        assert res.headers["x-aec-read-only"] == "1"
    # Auth stays outside the read-only check: a missing token is 401, not 405.
    assert client.post("/v1/ingestions", json={"path": "x"}).status_code == 401


def test_read_only_search_reaches_the_handler_and_ask_skips_the_model(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, read_only=True)
    search = client.post("/v1/search", headers=AUTH, json={"query": "wall"})
    assert search.status_code == 500

    class RecordingRAG:
        def __init__(self, db, settings, llm=None):
            self.llm = llm

        def ask(self, question, *, project=None, top_k=12, generate=True):
            return {"answer": "ok", "generate": generate, "called_model": self.llm is not None, "warnings": []}

    monkeypatch.setattr("aec_intelligence.operational.graphrag.ask.GraphRAG", RecordingRAG)
    ask = client.post("/v1/ask", headers=AUTH, json={"question": "벽은 어디에 있나", "generate": True})
    assert ask.status_code == 200
    body = ask.json()
    assert body["generate"] is False
    assert body["called_model"] is False
    assert "read-only deployment does not call a model" in body["warnings"]
    assert ask.headers["x-aec-canonical"] == "0"


def test_readonly_entrypoint_refuses_then_execs_uvicorn(monkeypatch):
    monkeypatch.setenv("AEC_API_READ_ONLY", "0")
    monkeypatch.setenv("AEC_API_TOKEN", TOKEN)
    monkeypatch.setenv("AEC_DATABASE_URL", "postgresql://aec:change-me@203.0.113.10:5432/aec")
    with pytest.raises(SystemExit, match="owner") as caught:
        readonly.main()
    assert "change-me" not in str(caught.value)
    assert TOKEN not in str(caught.value)

    monkeypatch.setenv("AEC_DATABASE_URL", READER_DSN)
    seen = {}

    def execvp(file, args):
        seen["file"] = file
        seen["args"] = args
        raise SystemExit(0)

    monkeypatch.setattr(os, "execvp", execvp)
    with pytest.raises(SystemExit):
        readonly.main()
    assert seen["file"] == "uvicorn"
    assert "aec_intelligence.operational.api:create_app" in seen["args"]
    assert "--factory" in seen["args"]
    assert os.environ["AEC_API_READ_ONLY"] == "1"


class _Conn:
    def __init__(self):
        self.statements: list[str] = []
        self.autocommit_values: list[bool] = []
        self._autocommit = False

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = value
        self.autocommit_values.append(value)

    def execute(self, query, params=None):
        self.statements.append(query)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_connect_sql_is_unchanged_unless_read_only(monkeypatch):
    monkeypatch.delenv("AEC_API_READ_ONLY", raising=False)
    holder = {}

    def connect(dsn, **kwargs):
        holder["conn"] = _Conn()
        return holder["conn"]

    monkeypatch.setattr("aec_intelligence.operational.db.psycopg.connect", connect)
    with Database("postgresql://aec:secret@127.0.0.1:55432/aec").connect():
        pass
    assert holder["conn"].autocommit_values == []
    assert holder["conn"].statements == [
        "LOAD 'age'",
        "SET search_path = ag_catalog, aec, public",
        "SET statement_timeout = '30s'",
    ]
    assert all("read_only" not in statement for statement in holder["conn"].statements)

    monkeypatch.setenv("AEC_API_READ_ONLY", "1")
    with Database("postgresql://aec_reader:secret@203.0.113.10:5432/aec").connect():
        assert holder["conn"].autocommit is False
    assert holder["conn"].autocommit_values == [True, False]
    assert holder["conn"].statements[-1] == "SET default_transaction_read_only = on"
    assert holder["conn"].statements[0] == "LOAD 'age'"


def test_pc_compose_and_scheduled_task_scripts_do_not_enable_read_only():
    compose = PC_COMPOSE.read_text(encoding="utf-8")
    assert "AEC_API_READ_ONLY" not in compose
    assert "aec-api-readonly" not in compose
    assert "aec-mobile-readonly" not in compose
    for path in OPS.glob("*.ps1"):
        text = path.read_text(encoding="utf-8")
        assert "AEC_API_READ_ONLY" not in text, path.name
        assert "mobile-readonly" not in text, path.name


def test_mobile_deploy_files_stay_off_the_pc_stack():
    compose = (DEPLOY / "compose.yml").read_text(encoding="utf-8")
    copy = (DEPLOY / "postgres-copy.yml").read_text(encoding="utf-8")
    role = (DEPLOY / "reader-role.sql").read_text(encoding="utf-8")
    example = (DEPLOY / "env.example").read_text(encoding="utf-8")
    for text in (compose, copy, role, example):
        assert "D:/AECData" not in text and "D:\\AECData" not in text
        assert "G:" not in text
        assert "switch-to-monorepo" not in text
        assert "change-me" not in text
        assert "PASSWORD '" not in text
    assert "name: aec-mobile-readonly" in compose
    assert "container_name: aec-api-readonly" in compose
    assert 'AEC_API_READ_ONLY: "1"' in compose
    assert "AEC_READONLY_API_TOKEN:?AEC_READONLY_API_TOKEN_is_required" in compose
    assert "AEC_READONLY_DATABASE_URL:?AEC_READONLY_DATABASE_URL_is_required" in compose
    assert "127.0.0.1:" in compose
    assert "read_only: true" in compose
    assert "python\", \"-m\", \"aec_intelligence.operational.readonly" in compose
    assert "\nvolumes:" not in compose
    assert "container_name: aec-db\n" not in compose
    assert "container_name: aec-api\n" not in compose
    assert "container_name: aec-db-copy" in copy
    assert "aec-mobile-pgdata" in copy
    assert "aec-pgdata:" not in copy
    assert "55433" in copy and "55432" not in copy
    assert "127.0.0.1:" in copy
    assert "AEC_COPY_DB_PASSWORD:?AEC_COPY_DB_PASSWORD_is_required" in copy
    assert "aec-api" not in copy
    assert "shared_preload_libraries=age" in copy
    assert "default_transaction_read_only" in role
    assert "GRANT INSERT" not in role and "GRANT ALL" not in role
    assert "CREATE ROLE aec_reader LOGIN" in role
    assert "AEC_READONLY_API_TOKEN=" in example
    assert "replace-with-token" not in example.split("AEC_READONLY_API_TOKEN=", 1)[-1].splitlines()[0]


DSN = os.getenv("AEC_TEST_DATABASE_URL")


@pytest.mark.skipif(not DSN, reason="AEC_TEST_DATABASE_URL not set")
def test_read_only_transaction_rejects_ddl_and_the_default_does_not(monkeypatch):
    import psycopg

    monkeypatch.setenv("AEC_API_READ_ONLY", "1")
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with Database(DSN).connect() as conn:
            conn.execute("CREATE TEMP TABLE aec_ro_probe(id int)")

    monkeypatch.delenv("AEC_API_READ_ONLY", raising=False)
    with Database(DSN).connect() as conn:
        conn.execute("CREATE TEMP TABLE aec_ro_probe(id int)")
        conn.execute("INSERT INTO aec_ro_probe(id) VALUES (1)")
        row = conn.execute("SELECT id FROM aec_ro_probe").fetchone()
    assert row["id"] == 1
