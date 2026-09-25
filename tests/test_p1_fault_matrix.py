"""P1 fault-oracle contracts for the security/data-first remediation wave.

Every test here is an exact oracle against production code. There are no
fallbacks, no ``pytest.skip`` escape hatches and no string-inspection proxies
for a gate that should be executed: each contract drives the real production
entry point and asserts the fail-closed outcome.

A failure therefore names a real production gap in the module named by the
test. It is fixed in that module, never weakened here.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from sion_api.db import Base, build_engine, build_session_factory
from sion_api.main import create_app
from sion_api.models import Artifact, Entity, Evidence, Relation
from sion_api.repository import seed_core_types
from sion_ingestion.agent_bridge import AgentSession
from sion_ingestion.bridge_cli import _data_root, _runtime_path, run_cycle
from sion_ingestion.dlp import DLPDecision, scan_payload
from sion_ingestion.map_import import (
    MapDLPError,
    MapExport,
    import_map_export,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sion_test_secret-abcdef123456"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_module():
    return _load(ROOT / "sync" / "sion_sync.py", "p1_sion_sync")


def _release_metadata_module():
    return _load(ROOT / "scripts" / "generate-release-metadata.py", "p1_release_metadata")


def _session_factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        seed_core_types(session)
    return factory


def _node(key: str, name: str = "P1 node", **extra) -> dict:
    payload = {
        "stable_key": key,
        "entity_type_id": "Project",
        "name": name,
        "properties": {},
    }
    payload.update(extra)
    return payload


def _export(nodes: list[dict], edges: list[dict] | None = None) -> MapExport:
    return MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "p1-fault-matrix",
            "nodes": nodes,
            "edges": edges or [],
        }
    )


def _edge(stable_key: str, source: str, target: str) -> dict:
    return {
        "stable_key": stable_key,
        "source_stable_key": source,
        "target_stable_key": target,
        "relation_type_id": "RELATED_TO",
    }


def _entities(session) -> list[Entity]:
    return list(session.scalars(select(Entity)))


def _bridge_args(**overrides) -> SimpleNamespace:
    values = {
        "export_out": "runtime/export.json",
        "pg_out": "runtime/export.sql",
        "graph_out": "runtime/export.md",
        "dry_run": False,
        "db_url": "sqlite://",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Engine:
    def dispose(self):
        return None


def _wire_bridge(monkeypatch, tmp_path, *, sessions=None, drive=None, import_error=None):
    """Wire the bridge cycle to deterministic providers and sinks.

    Only the *environment* is replaced (provider discovery, database handle,
    Drive detection). The DLP decision, the staging/publish primitives and the
    run_cycle control flow stay exactly as production wrote them.
    """
    found = sessions if sessions is not None else [
        AgentSession("synthetic-123456789", "codex", "clean", device_id="dev", cwd=str(tmp_path))
    ]
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli.PROVIDER_REGISTRY",
        {"codex": lambda: SimpleNamespace(discover=lambda limit=None: list(found))},
    )
    monkeypatch.setattr("sion_ingestion.bridge_cli.get_device_id", lambda: "dev")
    monkeypatch.setattr("sion_ingestion.bridge_cli.detect_google_drive_root", lambda: drive)
    monkeypatch.setattr("sion_api.db.build_engine", lambda url: _Engine())
    monkeypatch.setattr("sion_api.db.build_session_factory", lambda engine: (lambda: _NullSession()))
    monkeypatch.setattr("sion_api.repository.seed_core_types", lambda session: None)
    if import_error is None:
        monkeypatch.setattr(
            "sion_ingestion.bridge_cli.import_map_export",
            lambda session, export, already_scanned=None: SimpleNamespace(
                created_nodes=1, skipped_nodes=0, created_edges=0, skipped_edges=0
            ),
        )
    else:
        def _boom(session, export, already_scanned=None):
            raise import_error

        monkeypatch.setattr("sion_ingestion.bridge_cli.import_map_export", _boom)


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.txt").write_text("payload", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "x"],
        cwd=path, check=True, capture_output=True,
    )
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


# ---------------------------------------------------------------------------
# 1. API DLP sink
# ---------------------------------------------------------------------------

# A body per authenticated POST sink. The contract asserts that the complete
# POST surface of the application is covered here, so a new write sink cannot
# be added without a DLP oracle, and that each covered sink blocks a SECRET
# classification before any row is committed.
_API_SINK_BODIES = {
    "/api/v1/entities": lambda: {
        "stable_key": "project:p1-sink",
        "entity_type_id": "Project",
        "name": "sink",
        "properties": {"credential": SECRET},
    },
    "/api/v1/relations": lambda: {
        "stable_key": "project:p1-sink:RELATED_TO:project:p1-sink",
        "source_entity_id": "00000000-0000-0000-0000-000000000001",
        "target_entity_id": "00000000-0000-0000-0000-000000000002",
        "relation_type_id": "RELATED_TO",
        "properties": {"note": f"authorization: {SECRET}"},
    },
    "/api/v1/evidence": lambda: {
        "entity_id": "00000000-0000-0000-0000-000000000001",
        "artifact_id": "00000000-0000-0000-0000-000000000003",
        "source_uri": "urn:test:user-confirmed",
        "properties": {"excerpt": SECRET},
    },
    "/api/v1/artifacts": lambda: {
        "stable_key": "artifact:p1-sink",
        "name": "sample.dxf",
        "storage_uri": f"gdrive://token@{SECRET}/objects/sample.dxf",
        "properties": {},
    },
    "/api/v1/embeddings": lambda: {
        "entity_id": "00000000-0000-0000-0000-000000000001",
        "model": f"text-embedding-{SECRET}",
        "embedding": [1.0, 0.0, 0.0],
        "properties": {},
    },
    "/api/v1/vector/search": lambda: {
        "model": f"test/{SECRET}",
        "embedding": [1.0, 0.0, 0.0],
        "limit": 5,
    },
}

_SINK_MODELS = {
    "/api/v1/entities": Entity,
    "/api/v1/relations": Relation,
    "/api/v1/evidence": Evidence,
    "/api/v1/artifacts": Artifact,
    "/api/v1/embeddings": None,
    "/api/v1/vector/search": None,
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("SION_DLP_HMAC_KEY", raising=False)
    app = create_app(database_url=f"sqlite:///{tmp_path / 'p1-dlp.sqlite'}", auto_create_schema=True)
    with TestClient(app) as client:
        yield client, app


def _rows(app, model):
    if model is None:
        return []
    factory = build_session_factory(app.state.engine)
    with factory() as session:
        return list(session.scalars(select(model)))


def test_contract_every_post_write_sink_has_a_dlp_oracle():
    """Fail closed when the POST surface grows beyond the oracle set."""
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    post_sinks = {
        route.path
        for route in app.routes
        if "POST" in getattr(route, "methods", set())
    }
    assert post_sinks == set(_API_SINK_BODIES)


@pytest.mark.parametrize("sink", sorted(_API_SINK_BODIES))
def test_contract_api_dlp_sink_blocks_secret_before_commit(api, sink):
    client, app = api

    response = client.post(sink, json=_API_SINK_BODIES[sink]())

    assert response.status_code == 422, f"{sink} did not reject a SECRET payload: {response.text}"
    assert SECRET not in response.text
    assert _rows(app, _SINK_MODELS[sink]) == []


def test_contract_api_dlp_sink_rejects_when_scanner_is_unavailable(api, monkeypatch):
    """A missing scanner module must fail closed, not fail open."""
    client, app = api
    monkeypatch.setattr("sion_api.main._dlp_scan_payload", None)

    response = client.post("/api/v1/entities", json=_API_SINK_BODIES["/api/v1/entities"]())

    assert response.status_code == 422
    assert response.json()["detail"]["dlp"]["metadata"]["reason"] == "dlp_scanner_unavailable"
    assert _rows(app, Entity) == []


# ---------------------------------------------------------------------------
# 2. forged DLP decision
# ---------------------------------------------------------------------------


def test_contract_forged_dlp_decision_cannot_smuggle_a_secret_into_the_graph():
    """A caller-supplied ``allowed`` decision must not become a trust grant.

    ``import_map_export`` treats ``already_scanned`` as a trusted boundary. A
    forged decision that merely claims ``allowed=True`` and carries a raw,
    unscanned payload must be refused before canonical hashing and before any
    row is written.
    """
    factory = _session_factory()
    forged_payload = {
        "schema": "sion-map-export/v1",
        "source": "forged-decision",
        "nodes": [_node("project:forged", properties={"credential": SECRET})],
        "edges": [],
    }
    forged = DLPDecision(True, "allowed", forged_payload)
    caller_export = _export([_node("project:caller")])

    with factory() as session:
        try:
            import_map_export(session, caller_export, already_scanned=forged)
        except MapDLPError:
            pass
        else:
            pytest.fail(
                "FORGED_DLP_DECISION_CONTRACT: import_map_export accepted a "
                "caller-supplied DLPDecision(allowed=True) carrying an unscanned "
                "payload, so the trusted-boundary exception is an unauthenticated "
                "bypass of the DLP gate"
            )
        assert _entities(session) == []

    with factory() as session:
        assert _entities(session) == []


# ---------------------------------------------------------------------------
# 3. stale DLP decision
# ---------------------------------------------------------------------------


def test_contract_stale_dlp_decision_cannot_import_a_different_export():
    """A decision produced for another export must not authorise this one.

    The trusted decision carries no binding to the export being imported, so a
    decision for a different payload is silently accepted and the *decision's*
    payload is written. The contract requires a mismatch to fail closed.
    """
    factory = _session_factory()
    other = _export([_node("project:other", name="Other")])
    decision = scan_payload(other.model_dump(by_alias=True))
    caller_export = _export([_node("project:caller", name="Caller")])

    with factory() as session:
        try:
            result = import_map_export(session, caller_export, already_scanned=decision)
        except MapDLPError:
            pass
        else:
            pytest.fail(
                "STALE_DLP_DECISION_CONTRACT: import_map_export accepted a decision "
                f"scanned for a different export and imported {result.created_nodes} "
                "node(s) from that other payload; the trusted decision carries no "
                "binding to the export being imported"
            )
        assert _entities(session) == []


# ---------------------------------------------------------------------------
# 4. mismatched DLP decision
# ---------------------------------------------------------------------------


def test_contract_mismatched_tokenized_decision_fails_closed():
    """A ``tokenized`` decision whose sanitized payload is not an export is refused."""
    factory = _session_factory()
    decision = DLPDecision(False, "tokenized", {"not": "a map export"})

    with factory() as session:
        with pytest.raises(MapDLPError):
            import_map_export(
                session, _export([_node("project:mismatched")]), already_scanned=decision
            )
        assert _entities(session) == []


def test_contract_allowed_decision_with_non_mapping_payload_fails_closed():
    """``allowed=True`` with an unusable sanitized payload must not import the caller's export."""
    factory = _session_factory()
    decision = DLPDecision(True, "allowed", None)

    with factory() as session:
        with pytest.raises(MapDLPError):
            import_map_export(
                session, _export([_node("project:nonmapping")]), already_scanned=decision
            )
        assert _entities(session) == []


def test_contract_passing_two_trusted_decisions_is_refused():
    """Two trusted-boundary exceptions at once is always a caller bug."""
    factory = _session_factory()
    decision = scan_payload(_export([_node("project:one")]).model_dump(by_alias=True))

    with factory() as session:
        with pytest.raises(TypeError):
            import_map_export(
                session,
                _export([_node("project:one")]),
                already_scanned=decision,
                pre_sanitized=decision,
            )


# ---------------------------------------------------------------------------
# 5. edge endpoint hash change
# ---------------------------------------------------------------------------


def test_contract_edge_endpoint_change_under_a_stable_key_is_a_conflict():
    """Rewiring an existing edge under the same ``stable_key`` must not be skipped.

    ``edge_canonical_payload`` omits ``source_stable_key`` and
    ``target_stable_key``, so a rewire produces an identical hash and the
    import reports a skip while the stored graph keeps the old endpoints.
    """
    factory = _session_factory()
    nodes = [_node("project:a"), _node("project:b"), _node("project:c")]
    first = _export(nodes, [_edge("edge:1", "project:a", "project:b")])
    rewired = _export(nodes, [_edge("edge:1", "project:a", "project:c")])

    with factory() as session:
        import_map_export(session, first)

    with factory() as session:
        try:
            result = import_map_export(session, rewired)
        except Exception as exc:
            assert type(exc).__name__ == "GraphIdentityConflictError", (
                f"EDGE_ENDPOINT_CHANGE_CONTRACT: expected GraphIdentityConflictError, "
                f"got {type(exc).__name__}: {exc}"
            )
            assert "edge:1" in str(exc)
        else:
            pytest.fail(
                "EDGE_ENDPOINT_CHANGE_CONTRACT: rewiring edge:1 from project:b to "
                f"project:c was reported as a skip "
                f"(created={result.created_edges}, skipped={result.skipped_edges}); "
                "edge_canonical_payload omits source/target stable keys, so the "
                "stored graph silently keeps the previous endpoints"
            )


# ---------------------------------------------------------------------------
# 6. bridge staging failure
# ---------------------------------------------------------------------------


def test_contract_bridge_staging_failure_publishes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    drive = tmp_path / "drive"
    drive.mkdir()
    _wire_bridge(monkeypatch, tmp_path, drive=drive)
    monkeypatch.setattr(
        "sion_ingestion.bridge_cli._write_staged",
        lambda path, content: (_ for _ in ()).throw(OSError("injected staging failure")),
    )

    assert run_cycle(_bridge_args(), ["codex"], None) == 1
    assert not (tmp_path / "data" / "runtime" / "export.json").exists()
    assert not list(drive.rglob("*.sql"))
    assert not list(drive.rglob("*.json"))
    assert not list(drive.rglob("*.md"))


# ---------------------------------------------------------------------------
# 7. bridge read-back failure
# ---------------------------------------------------------------------------


def test_contract_bridge_readback_failure_publishes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    drive = tmp_path / "drive"
    drive.mkdir()
    _wire_bridge(monkeypatch, tmp_path, drive=drive)
    real_verify = __import__("sion_ingestion.bridge_cli", fromlist=["_verify_digest"])._verify_digest

    def fail_staging_readback(path, digest, size, label):
        if label == "staging":
            raise OSError("injected read-back failure")
        return real_verify(path, digest, size, label)

    monkeypatch.setattr("sion_ingestion.bridge_cli._verify_digest", fail_staging_readback)

    assert run_cycle(_bridge_args(), ["codex"], None) == 1
    assert "staging failed" in capsys.readouterr().out
    assert not (tmp_path / "data" / "runtime" / "export.json").exists()
    assert not list(drive.rglob("*.sql"))
    assert not list(drive.rglob("*.json"))
    assert not list(drive.rglob("*.md"))


def test_contract_bridge_publish_readback_mismatch_leaves_previous_target(tmp_path, monkeypatch):
    """A corrupted staging copy must never replace an already published artifact."""
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _wire_bridge(monkeypatch, tmp_path, drive=None)
    root = _data_root()
    target = _runtime_path("runtime/export.json", root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"previous": true}', encoding="utf-8")

    import sion_ingestion.bridge_cli as cli

    real_copy = cli.shutil.copy2

    def corrupt_first_copy(src, dst, *args, **kwargs):
        real_copy(src, dst, *args, **kwargs)
        Path(dst).write_text("corrupted", encoding="utf-8")
        return dst

    monkeypatch.setattr("sion_ingestion.bridge_cli.shutil.copy2", corrupt_first_copy)

    assert run_cycle(_bridge_args(), ["codex"], None) == 1
    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    assert not list(target.parent.glob("*.sion-publish.tmp"))


# ---------------------------------------------------------------------------
# 8. incomplete canonical snapshot
# ---------------------------------------------------------------------------


def test_contract_incomplete_canonical_snapshot_is_never_treated_as_published(tmp_path):
    sync = _sync_module()
    head = _git_repo(tmp_path / "repo")
    root = tmp_path / "drive" / "canonical" / "proj"

    cases = {
        "missing_snapshot_json": ({"partial": "x"}, None),
        "missing_complete": ({}, {"_snapshot.json": {"schema": "sion-canonical-snapshot/v3", "git_sha": head,
                                                     "run_id": "r", "timestamp_utc": "t", "file_count": 1,
                                                     "project": "proj"}}),
        "empty_run_id": (
            {".complete": {"run_id": "", "git_sha": head},
             "_snapshot.json": {"schema": "sion-canonical-snapshot/v3", "git_sha": head, "run_id": "",
                                "timestamp_utc": "t", "file_count": 1, "project": "proj"}},
            None,
        ),
        "foreign_git_sha": (
            {".complete": {"run_id": "r", "git_sha": "0" * 40},
             "_snapshot.json": {"schema": "sion-canonical-snapshot/v3", "git_sha": "0" * 40, "run_id": "r",
                                "timestamp_utc": "t", "file_count": 1, "project": "proj"}},
            None,
        ),
        "wrong_project": (
            {".complete": {"run_id": "r", "git_sha": head},
             "_snapshot.json": {"schema": "sion-canonical-snapshot/v3", "git_sha": head, "run_id": "r",
                                "timestamp_utc": "t", "file_count": 1, "project": "other"}},
            None,
        ),
    }

    for name, (files, _extra) in cases.items():
        dest = root / f"{head}-{name}"
        dest.mkdir(parents=True)
        for filename, content in files.items():
            target = dest / filename
            target.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        valid, meta = sync._valid_published_snapshot(dest, head, "proj")
        assert valid is False, f"{name} was accepted as a published snapshot"
        assert meta is None


def test_contract_promote_quarantines_incomplete_destination_and_binds_run_id(tmp_path, capsys):
    sync = _sync_module()
    head = _git_repo(tmp_path / "repo")
    drive = tmp_path / "drive"
    incomplete = drive / "canonical" / "proj" / head
    incomplete.mkdir(parents=True)
    (incomplete / "partial").write_text("partial", encoding="utf-8")

    assert sync.promote(
        argparse.Namespace(project=str(tmp_path / "repo"), drive_root=str(drive), project_name="proj")
    ) == 0

    captured = capsys.readouterr()
    assert "quarantined-incomplete" in captured.err
    published = drive / "canonical" / "proj" / head
    snapshot = json.loads((published / "_snapshot.json").read_text(encoding="utf-8"))
    complete = json.loads((published / ".complete").read_text(encoding="utf-8"))
    latest = json.loads((drive / "canonical" / "proj" / "latest.json").read_text(encoding="utf-8"))
    assert snapshot["git_sha"] == complete["git_sha"] == latest["git_sha"] == head
    assert snapshot["run_id"] == complete["run_id"] == latest["run_id"]
    assert snapshot["run_id"]
    assert not list((drive / "canonical" / "proj").glob(".staging-*"))


def test_contract_promote_pointer_write_failure_is_reported(tmp_path):
    """A published snapshot whose latest pointer failed must raise, not report success."""
    sync = _sync_module()
    _git_repo(tmp_path / "repo")
    drive = tmp_path / "drive"
    real_write = sync.write_json

    def fail_latest(path, data):
        if str(path).endswith("latest.json"):
            raise OSError("injected pointer failure")
        return real_write(path, data)

    sync.write_json = fail_latest
    try:
        with pytest.raises(RuntimeError):
            sync.promote(
                argparse.Namespace(
                    project=str(tmp_path / "repo"), drive_root=str(drive), project_name="proj"
                )
            )
    finally:
        sync.write_json = real_write

    assert not list((drive / "canonical" / "proj").glob(".staging-*"))


# ---------------------------------------------------------------------------
# 9. partial metadata set
# ---------------------------------------------------------------------------


def test_contract_release_metadata_publishes_the_complete_set(tmp_path):
    meta = _release_metadata_module()
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    out_dir = tmp_path / "release-metadata"

    meta.generate(tmp_path, out_dir, [artifact])

    assert {p.name for p in out_dir.iterdir()} >= {
        "release-metadata.json", "provenance.json", "SHA256SUMS"
    }
    provenance = json.loads((out_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["signature_status"] == "not_signed"
    assert provenance["verified"] is False


def test_contract_post_commit_failure_leaves_no_partial_or_stale_set(tmp_path):
    """If an input changes after the commit, nothing stale may stay published."""
    meta = _release_metadata_module()
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    out_dir = tmp_path / "release-metadata"
    real_recheck = meta.recheck

    def mutate_after_commit(observed, phase):
        if phase == "after":
            artifact.write_bytes(b"changed-after-commit")
        return real_recheck(observed, phase)

    meta.recheck = mutate_after_commit
    try:
        with pytest.raises(meta.ReleaseMetadataError):
            meta.generate(tmp_path, out_dir, [artifact])
    finally:
        meta.recheck = real_recheck

    assert not out_dir.exists(), "a partial or stale metadata set remained published"
    siblings = [p.name for p in out_dir.parent.iterdir()] if out_dir.parent.exists() else []
    assert not [name for name in siblings if name.startswith(".release-metadata.staging-")]
    assert not [name for name in siblings if name.startswith(".release-metadata.previous-")]


def test_contract_incomplete_previous_set_is_never_restored(tmp_path):
    """A displaced set missing provenance must not be republished as current."""
    meta = _release_metadata_module()
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    backup = tmp_path / "previous"
    backup.mkdir()
    (backup / "release-metadata.json").write_text(
        json.dumps({"artifacts": [{"name": "artifact.bin", "sha256": "0" * 64, "size": 7}]}),
        encoding="utf-8",
    )
    observed = meta.snapshot_inputs(tmp_path, [artifact])

    assert meta._previous_set_is_current(backup, observed) is False


# ---------------------------------------------------------------------------
# 10. NotTrusted signing
# ---------------------------------------------------------------------------


def test_contract_nottrusted_signature_is_not_accepted_as_signed(tmp_path):
    """``NotTrusted`` means the chain does not validate; it must block release.

    ``preflight-signing.ps1`` decides release eligibility with a single
    PowerShell expression. The expression itself is evaluated here against every
    authenticode status, so the oracle is the production rule and not a text
    match against it.
    """
    script = (ROOT / "scripts" / "preflight-signing.ps1").read_text(encoding="utf-8-sig")
    accept_lines = [
        line.strip() for line in script.splitlines()
        if "$signed" in line and "-in" in line
    ]
    assert len(accept_lines) == 1, f"unexpected signed-state expression: {accept_lines}"
    expression = accept_lines[0].split("=", 1)[1].strip()

    harness = (
        "param([string]$authenticodeStatus)\n"
        "$signed = " + expression + "\n"
        "Write-Output $signed\n"
    )
    harness_path = tmp_path / "signed-expression.ps1"
    harness_path.write_text(harness, encoding="utf-8-sig")
    verdicts = {}
    for status in ("Valid", "NotTrusted", "NotSigned", "UnknownError", "Unavailable"):
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(harness_path), "-authenticodeStatus", status],
            capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        verdicts[status] = completed.stdout.strip() == "True"

    assert verdicts["Valid"] is True, "a Valid signature is not accepted as signed"
    assert verdicts["NotTrusted"] is False, (
        "preflight-signing.ps1 accepts a NotTrusted authenticode status as a signed "
        "release artifact; a signature from an untrusted chain is not a release signature"
    )
    for status in ("NotSigned", "UnknownError", "Unavailable"):
        assert verdicts[status] is False, f"{status} was accepted as signed"


def test_contract_signing_preflight_blocks_a_not_trusted_artifact(tmp_path):
    """Behavioural oracle: an untrusted-chain artifact must block, not pass."""
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "bin" / "tool.exe").write_bytes(b"unsigned payload")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "bin/tool.exe"], check=True, capture_output=True)

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "preflight-signing.ps1"), "-RepoRoot", str(repo)],
        capture_output=True, text=True,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    report = repo / "tmp" / "signing-preflight" / "signing-preflight.json"
    payload = json.loads(report.read_text(encoding="utf-8-sig"))
    for artifact in payload["artifacts"]:
        assert artifact["signed"] is (artifact["authenticode_status"] == "Valid"), (
            f"authenticode status {artifact['authenticode_status']} was reported as "
            f"signed={artifact['signed']}"
        )
    assert payload["unsigned_release_block"]["blocked"] is True


# ---------------------------------------------------------------------------
# 11. absent CI
# ---------------------------------------------------------------------------


def test_contract_absent_or_untriggered_ci_cannot_be_read_as_green():
    """The workflow must run on the release branch and on every pull request."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert "pull_request" in triggers, "CI does not run for pull requests"
    assert triggers["pull_request"] in (None, {}), "pull_request trigger is restricted"
    assert "codex/p0-remediation-20260924" in triggers["push"]["branches"]


def test_contract_every_ci_job_is_ungated_and_bounded():
    """No job or step may be skipped, tolerated or left unbounded."""
    raw = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "pytest-suite", "alembic-revision-contract", "postgres-core",
        "postgres-pgvector", "resource-wheel-contract", "secret-scan",
    }
    for name, job in jobs.items():
        assert "if" not in job, f"job {name} is conditional and may be skipped"
        assert "continue-on-error" not in job, f"job {name} tolerates failure"
        assert "timeout-minutes" in job, f"job {name} has no timeout"
        for step in job.get("steps", []):
            assert "continue-on-error" not in step, f"a step in {name} tolerates failure"
            assert "if" not in step, f"a step in {name} is conditional and may be skipped"
    assert "continue-on-error" not in raw
    assert "if: always()" not in raw
    assert "|| true" not in raw


# ---------------------------------------------------------------------------
# 12. billing-blocked CI
# ---------------------------------------------------------------------------


def test_contract_billing_blocked_or_absent_run_is_documented_as_a_blocker():
    checklist = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    lowered = checklist.lower()
    for phrase in ("billing", "not** a successful ci result", "release blocker"):
        assert phrase in lowered, f"release checklist no longer states {phrase!r} as a blocker"


# ---------------------------------------------------------------------------
# 13. migration preflight
# ---------------------------------------------------------------------------


def _bind(module, connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module.op = Operations(MigrationContext.configure(connection))
    return module


def _legacy_database(engine):
    from sqlalchemy import text

    connection = engine.connect()
    connection.execute(text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, content_hash VARCHAR(200))"))
    connection.execute(text("CREATE TABLE chunks (id VARCHAR PRIMARY KEY, ordinal INTEGER)"))
    connection.execute(
        text("CREATE TABLE relations (id VARCHAR PRIMARY KEY, source_entity_id VARCHAR, "
             "target_entity_id VARCHAR, valid_from DATETIME, valid_to DATETIME)")
    )
    connection.execute(
        text("CREATE TABLE evidence (id VARCHAR PRIMARY KEY, entity_id VARCHAR, relation_id VARCHAR, "
             "artifact_id VARCHAR, chunk_id VARCHAR, source_uri TEXT, excerpt_hash VARCHAR(200), "
             "confidence FLOAT, verification_state VARCHAR(30) NOT NULL DEFAULT 'unverified')")
    )
    return connection


def test_contract_migration_preflight_is_read_only_on_a_conforming_database():
    from sqlalchemy import create_engine, text

    module = _load(ROOT / "migrations" / "versions" / "0002_evidence_contract.py", "p1_0002_readonly")
    connection = _legacy_database(create_engine("sqlite://"))
    connection.execute(text("INSERT INTO artifacts VALUES ('a1', NULL)"))
    connection.execute(text("INSERT INTO chunks VALUES ('c1', 0)"))
    connection.execute(
        text("INSERT INTO evidence (id, entity_id, artifact_id, chunk_id, verification_state) "
             "VALUES ('e1', 'ent', 'a1', 'c1', 'unverified')")
    )
    _bind(module, connection)

    before = connection.execute(text("SELECT count(*) FROM evidence")).scalar_one()
    assert module.preflight() == []
    after = connection.execute(text("SELECT count(*) FROM evidence")).scalar_one()
    assert before == after == 1


def test_contract_migration_preflight_reports_every_legacy_violation_class():
    from sqlalchemy import create_engine, text

    module = _load(ROOT / "migrations" / "versions" / "0002_evidence_contract.py", "p1_0002_violations")
    connection = _legacy_database(create_engine("sqlite://"))
    connection.execute(
        text("INSERT INTO evidence (id, entity_id, verification_state) VALUES ('e1', 'ent', 'unverified')")
    )
    connection.execute(text("INSERT INTO relations VALUES ('r1', 'e1', 'e1', NULL, NULL)"))
    connection.execute(
        text("INSERT INTO evidence (id, entity_id, relation_id, source_uri, excerpt_hash, "
             "verification_state) VALUES ('e2', 'ent', 'rel', 's3://b/x', "
             "'md5:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef', 'unverified')")
    )
    connection.execute(
        text("INSERT INTO evidence (id, entity_id, artifact_id, verification_state) "
             "VALUES ('e3', 'ent', 'missing-artifact', 'unverified')")
    )
    _bind(module, connection)

    with pytest.raises(RuntimeError) as raised:
        module.preflight()

    message = str(raised.value)
    for constraint in (
        "ck_evidence_source", "ck_evidence_target_xor", "ck_evidence_excerpt_hash",
        "ck_relation_no_self_loop", "fk_evidence_artifact_id",
    ):
        assert constraint in message, f"preflight did not report {constraint}"


# ---------------------------------------------------------------------------
# 14. legacy violation at migration time
# ---------------------------------------------------------------------------


def test_contract_evidence_migration_refuses_to_mutate_a_violating_database():
    """``upgrade()`` must fail before any constraint or column is added."""
    from sqlalchemy import create_engine, inspect, text

    module = _load(ROOT / "migrations" / "versions" / "0002_evidence_contract.py", "p1_0002_upgrade")
    connection = _legacy_database(create_engine("sqlite://"))
    connection.execute(
        text("INSERT INTO evidence (id, entity_id, verification_state) VALUES ('e1', 'ent', 'unverified')")
    )
    _bind(module, connection)

    with pytest.raises(RuntimeError):
        module.upgrade()

    checks = {c["name"] for c in inspect(connection).get_check_constraints("evidence")}
    assert not checks, f"0002 left constraints behind after failing: {sorted(checks)}"


def test_contract_parity_migration_preflights_before_widening_or_adding_checks():
    """0004 must inspect legacy data before applying parity DDL.

    ``0004_schema_parity`` has no ``preflight``. On a legacy database with a
    row that violates the check it is about to add, the column widenings are
    committed and the migration then aborts with a raw ``IntegrityError``,
    leaving the database partially migrated.
    """
    from sqlalchemy import create_engine, inspect, text

    module = _load(ROOT / "migrations" / "versions" / "0004_schema_parity.py", "p1_0004")
    assert hasattr(module, "preflight"), (
        "0004_schema_parity has no preflight, so a legacy violation is discovered "
        "only after earlier parity DDL has been committed"
    )
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, name VARCHAR(200), "
             "provider_file_id VARCHAR(200), byte_size INTEGER, content_hash VARCHAR(200))")
    )
    connection.execute(
        text("CREATE TABLE documents (id VARCHAR PRIMARY KEY, title VARCHAR(500), language VARCHAR(20))")
    )
    connection.execute(
        text("CREATE TABLE relations (id VARCHAR PRIMARY KEY, stable_key VARCHAR(500), "
             "verification_state VARCHAR(30), confidence FLOAT, source_entity_id VARCHAR, "
             "target_entity_id VARCHAR)")
    )
    connection.execute(text("CREATE TABLE chunks (id VARCHAR PRIMARY KEY, ordinal INTEGER)"))
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) VALUES ('a1', 'f', 'f', -5)")
    )
    _bind(module, connection)

    with pytest.raises(RuntimeError):
        module.upgrade()

    inspector = inspect(connection)
    artifacts = next(
        c for c in inspector.get_columns("artifacts") if c["name"] == "provider_file_id"
    )
    assert artifacts["type"].length == 200, (
        "0004 widened provider_file_id before failing on the legacy byte_size violation"
    )


# ---------------------------------------------------------------------------
# 15. run_id / stale lock
# ---------------------------------------------------------------------------


def _host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"


def test_contract_stale_lock_from_another_host_is_never_reclaimed(tmp_path):
    """PID namespaces differ across hosts, so a foreign lock is not stale."""
    sync = _sync_module()
    lock = tmp_path / ".sion-sync.lock"
    lock.write_text(json.dumps({"pid": 4242, "host": "some-other-host", "created": 0.0}), encoding="utf-8")

    with pytest.raises(RuntimeError):
        with sync.sync_lock(lock, timeout=0.0):
            pass
    assert lock.exists()


def test_contract_live_owner_lock_is_never_reclaimed(tmp_path):
    sync = _sync_module()
    lock = tmp_path / ".sion-sync.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "host": _host(), "created": time.time() - 10_000}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        with sync.sync_lock(lock, timeout=0.0):
            pass
    assert lock.exists()


def test_contract_dead_owner_lock_on_same_host_is_reclaimed_and_released(tmp_path):
    sync = _sync_module()
    lock = tmp_path / ".sion-sync.lock"
    lock.write_text(
        json.dumps({"pid": 999_999, "host": _host(), "created": time.time() - 10_000}),
        encoding="utf-8",
    )

    with sync.sync_lock(lock, timeout=0.0):
        record = json.loads(lock.read_text(encoding="utf-8"))
        assert set(record) == {"pid", "host", "created"}
        assert record["pid"] == os.getpid()
    assert not lock.exists()


def test_contract_corrupt_lock_fails_closed_instead_of_being_reclaimed(tmp_path):
    sync = _sync_module()
    lock = tmp_path / ".sion-sync.lock"
    lock.write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with sync.sync_lock(lock, timeout=0.0):
            pass
    assert lock.exists()


def test_contract_every_backup_attempt_records_a_distinct_run_id(tmp_path):
    sync = _sync_module()
    source = tmp_path / "ws"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    args = argparse.Namespace(
        source=str(source), drive_root=str(tmp_path / "drive"),
        state_dir=str(tmp_path / "state"), device_id="dev", workspace_name="ws",
    )

    assert sync.backup(args) == 0
    first = json.loads((tmp_path / "state" / "dev-ws.json").read_text(encoding="utf-8"))
    assert sync.backup(args) == 0
    second = json.loads((tmp_path / "state" / "dev-ws.json").read_text(encoding="utf-8"))

    assert first["last_success"]["run_id"] != second["last_success"]["run_id"]
    assert (second["attempts"], first["attempts"]) == (2, 1)
    assert second["last_success"]["verified_atomic"] is True


# ---------------------------------------------------------------------------
# 16. no-session exit
# ---------------------------------------------------------------------------


def test_contract_no_session_exit_is_two_and_persists_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    _wire_bridge(monkeypatch, tmp_path, sessions=[])

    assert run_cycle(_bridge_args(), ["codex"], None) == 2
    assert not (tmp_path / "data").exists()
    assert list(tmp_path.iterdir()) == []


def test_contract_no_session_exit_precedes_every_sink_boundary(tmp_path, monkeypatch):
    """A session-less cycle must not reach DLP, staging, the DB or Drive."""
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))

    def must_not_run(*args, **kwargs):
        raise AssertionError("a sink boundary ran for a session-less cycle")

    _wire_bridge(monkeypatch, tmp_path, sessions=[])
    monkeypatch.setattr("sion_ingestion.bridge_cli.scan_payload", must_not_run)
    monkeypatch.setattr("sion_ingestion.bridge_cli._write_staged", must_not_run)
    monkeypatch.setattr("sion_ingestion.bridge_cli._atomic_publish", must_not_run)

    assert run_cycle(_bridge_args(), ["codex"], None) == 2


# ---------------------------------------------------------------------------
# 17. path containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("candidate", ["../escape.json", "nested/../../escape.json"])
def test_contract_runtime_path_rejects_parent_traversal(tmp_path, monkeypatch, candidate):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))

    with pytest.raises(ValueError):
        _runtime_path(candidate, _data_root())


def test_contract_runtime_path_rejects_absolute_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    outside = tmp_path / "outside" / "export.json"
    outside.parent.mkdir()

    with pytest.raises(ValueError):
        _runtime_path(str(outside), _data_root())


def test_contract_runtime_path_contains_every_default_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_DATA_ROOT", str(tmp_path / "data"))
    root = _data_root()
    for name in ("agent_export.json", "sion_pg_knowledge_graph.sql", "agent_graph.md",
                 "runtime/sion.db"):
        assert _runtime_path(name, root).is_relative_to(root)


@pytest.mark.parametrize("configured", ["_MEIPASS", "inside_repo"])
def test_contract_data_root_rejects_repository_and_bundle_locations(tmp_path, monkeypatch, configured):
    if configured == "_MEIPASS":
        candidate = tmp_path / "_MEIPASS" / "data"
    else:
        candidate = ROOT / "runtime" / "p1-data-root"
    monkeypatch.setenv("SION_DATA_ROOT", str(candidate))

    with pytest.raises(ValueError):
        _data_root()
