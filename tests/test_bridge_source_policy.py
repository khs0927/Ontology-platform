"""Source-policy contract for the agent ontology bridge.

Three properties are locked down here:

1. A normal, legitimate export is **not** quarantined by the DLP gate.  The
   scanner raises an INTERNAL finding for any key literally named
   ``source_uri``, which maps to ``quarantine``, so the bridge must emit a
   logical reference under a different key instead.
2. No raw absolute path and no user-home component reaches a sink; locators
   are replaced by deterministic opaque tokens.
3. Identity stays deterministic and backward compatible, and oversized or
   malformed transcripts produce explicit diagnostics rather than silence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sion_ingestion.agent_bridge import (
    MIN_TRANSCRIPT_BYTES,
    MAX_TRANSCRIPT_BYTES,
    SOURCE_TOKEN_KEY_ENV,
    STATUS_MALFORMED,
    STATUS_OVERSIZED,
    STATUS_OK,
    AgentOntologyBridge,
    AgentSession,
    ClaudeReader,
    CodexReader,
    logical_source_reference,
    opaque_source_token,
    resolve_source_token_key,
)
from sion_ingestion.dlp import scan_payload
from sion_ingestion.map_import import MapExport


SYNTHETIC_TOKEN_KEY = b"synthetic-bridge-source-policy-key-not-for-production"

# A raw location shaped like a real user home, so leakage is detectable.
FAKE_HOME = "/home/synthetic-user/sion/transcripts"
FAKE_CWD = f"{FAKE_HOME}/workspace/project-alpha"
FAKE_SOURCE_URI = f"file://{FAKE_HOME}/ses_abcdef012345.jsonl"


def a_session(**overrides) -> AgentSession:
    values = dict(
        session_id="ses_abcdef012345",
        provider="claude",
        title="Refactor the ingestion pipeline",
        device_id="synthetic-device",
        cwd=FAKE_CWD,
        created_at="2026-01-02T03:04:05+00:00",
        tools={"Read", "Edit"},
        artifacts={"main.py"},
        decisions=["Plan created: implementation_plan.md"],
        source_uri=FAKE_SOURCE_URI,
    )
    values.update(overrides)
    return AgentSession(**values)


def exported_nodes(export: MapExport, entity_type_id: str) -> list[dict]:
    return [n for n in export.nodes if n.entity_type_id == entity_type_id]


# --------------------------------------------------------------------------
# 1. Normal exports must not be quarantined
# --------------------------------------------------------------------------


def test_normal_export_is_allowed_by_dlp_gate():
    """Regression: a clean session used to be quarantined unconditionally."""
    export = AgentOntologyBridge().convert_sessions_to_map_export([a_session()])
    decision = scan_payload(export.model_dump(by_alias=True), cwd="/synthetic/data-root")

    assert decision.allowed, [f.to_dict() for f in decision.findings]
    assert decision.findings == ()


def test_export_never_uses_a_source_uri_key():
    """`source_uri` is an unconditional INTERNAL finding, so the key is banned."""
    export = AgentOntologyBridge().convert_sessions_to_map_export([a_session()])
    payload = json.dumps(export.model_dump(by_alias=True))

    assert '"source_uri"' not in payload
    for node in export.nodes:
        assert "source_uri" not in node.properties


def test_full_pipeline_export_survives_dlp_for_every_provider():
    for provider in ("claude", "codex", "antigravity"):
        export = AgentOntologyBridge().convert_sessions_to_map_export(
            [a_session(provider=provider, source_uri=f"file://{FAKE_HOME}/{provider}.jsonl")]
        )
        decision = scan_payload(export.model_dump(by_alias=True), cwd="/synthetic/data-root")
        assert decision.allowed, f"{provider}: {[f.to_dict() for f in decision.findings]}"


# --------------------------------------------------------------------------
# 2. No raw path or user name in any sink
# --------------------------------------------------------------------------


def test_no_raw_path_or_user_name_reaches_the_export():
    export = AgentOntologyBridge().convert_sessions_to_map_export([a_session()])
    payload = json.dumps(export.model_dump(by_alias=True), ensure_ascii=False)

    assert FAKE_HOME not in payload
    assert FAKE_CWD not in payload
    assert FAKE_SOURCE_URI not in payload
    assert "synthetic-user" not in payload
    assert "file:///" not in payload


def test_workflow_carries_logical_reference_and_opaque_token():
    export = AgentOntologyBridge(source_token_key=SYNTHETIC_TOKEN_KEY).convert_sessions_to_map_export(
        [a_session()]
    )
    (workflow,) = exported_nodes(export, "Workflow")
    props = workflow.properties

    assert props["source_reference"] == "urn:sion:agent-session:claude:ses_abcdef012345"
    assert props["source_token"].startswith("urn:sion:source-token:")
    assert FAKE_SOURCE_URI not in props["source_token"]
    # The token must be stable for the same key, so identity survives re-runs.
    assert props["source_token"] == opaque_source_token(FAKE_SOURCE_URI, SYNTHETIC_TOKEN_KEY)


def test_project_stores_cwd_as_token_not_raw_path():
    export = AgentOntologyBridge(source_token_key=SYNTHETIC_TOKEN_KEY).convert_sessions_to_map_export(
        [a_session()]
    )
    (project,) = exported_nodes(export, "Project")

    assert "cwd" not in project.properties
    assert project.properties["cwd_token"] == opaque_source_token(FAKE_CWD, SYNTHETIC_TOKEN_KEY)
    assert FAKE_CWD not in json.dumps(project.model_dump(by_alias=True))


def test_tokens_differ_per_key_but_are_deterministic_within_a_key():
    first = opaque_source_token(FAKE_CWD, SYNTHETIC_TOKEN_KEY)
    second = opaque_source_token(FAKE_CWD, b"a-different-synthetic-key")

    assert first == opaque_source_token(FAKE_CWD, SYNTHETIC_TOKEN_KEY)
    assert first != second


# --------------------------------------------------------------------------
# 3. CLI-injectable key via environment
# --------------------------------------------------------------------------


def test_source_token_key_is_injectable_from_environment(monkeypatch):
    monkeypatch.setenv(SOURCE_TOKEN_KEY_ENV, "env-injected-synthetic-key")
    assert resolve_source_token_key() == b"env-injected-synthetic-key"
    assert opaque_source_token(FAKE_CWD) == opaque_source_token(FAKE_CWD, "env-injected-synthetic-key")


def test_explicit_key_argument_wins_over_environment(monkeypatch):
    monkeypatch.setenv(SOURCE_TOKEN_KEY_ENV, "env-injected-synthetic-key")
    assert resolve_source_token_key(SYNTHETIC_TOKEN_KEY) == SYNTHETIC_TOKEN_KEY


def test_bridge_picks_up_environment_key_without_constructor_argument(monkeypatch):
    monkeypatch.setenv(SOURCE_TOKEN_KEY_ENV, "env-injected-synthetic-key")
    export = AgentOntologyBridge().convert_sessions_to_map_export([a_session()])
    (workflow,) = exported_nodes(export, "Workflow")

    assert workflow.properties["source_token"] == opaque_source_token(
        FAKE_SOURCE_URI, "env-injected-synthetic-key"
    )


def test_missing_key_falls_back_to_deterministic_default(monkeypatch):
    monkeypatch.delenv(SOURCE_TOKEN_KEY_ENV, raising=False)
    resolved = resolve_source_token_key()

    assert resolved  # never empty
    assert opaque_source_token(FAKE_CWD) == opaque_source_token(FAKE_CWD)


def test_logical_reference_is_stable_and_carries_no_filesystem_detail():
    reference = logical_source_reference("claude", "ses_abcdef012345")

    assert reference == logical_source_reference("claude", "ses_abcdef012345")
    assert reference == "urn:sion:agent-session:claude:ses_abcdef012345"
    assert reference.startswith("urn:sion:agent-session:")
    # No drive letter, no path separator, no user-home component.
    assert "/" not in reference and "\\" not in reference
    assert not Path(reference).exists()


# --------------------------------------------------------------------------
# 4. Deterministic identity / backward compatibility
# --------------------------------------------------------------------------


def test_stable_keys_are_unchanged_by_the_source_policy():
    """stable_key format must not drift, or every existing row re-keys."""
    session = a_session()
    keys = {n.stable_key for n in exported_nodes(AgentOntologyBridge().convert_sessions_to_map_export([session]), "Workflow")}
    import hashlib

    expected_cwd_hash = hashlib.sha256(session.cwd.encode("utf-8")).hexdigest()
    assert keys == {
        f"workflow:claude:synthetic-device:{session.session_id}:{expected_cwd_hash}"
    }


def test_identity_is_stable_across_repeated_exports():
    session = a_session()
    first = AgentOntologyBridge(source_token_key=SYNTHETIC_TOKEN_KEY).convert_sessions_to_map_export([session])
    second = AgentOntologyBridge(source_token_key=SYNTHETIC_TOKEN_KEY).convert_sessions_to_map_export([session])

    assert [n.model_dump() for n in first.nodes] == [n.model_dump() for n in second.nodes]
    assert [e.model_dump() for e in first.edges] == [e.model_dump() for e in second.edges]


def test_distinct_cwds_still_produce_distinct_workflow_keys():
    bridge = AgentOntologyBridge()
    a = bridge.convert_sessions_to_map_export([a_session(cwd=FAKE_CWD)])
    b = bridge.convert_sessions_to_map_export([a_session(cwd=f"{FAKE_CWD}-other")])

    a_keys = {n.stable_key for n in exported_nodes(a, "Workflow")}
    b_keys = {n.stable_key for n in exported_nodes(b, "Workflow")}
    assert a_keys != b_keys


def test_sanitized_export_still_validates_as_map_export():
    export = AgentOntologyBridge().convert_sessions_to_map_export([a_session()])
    decision = scan_payload(export.model_dump(by_alias=True), cwd="/synthetic/data-root")

    assert decision.allowed
    revalidated = MapExport.model_validate(decision.sanitized_payload)
    assert revalidated.expected_node_count == len(export.nodes)
    assert revalidated.expected_edge_count == len(export.edges)


# --------------------------------------------------------------------------
# 5. Oversized / malformed session diagnostics
# --------------------------------------------------------------------------


def _write_claude_transcript(directory, name: str, body: str):
    """Write a transcript padded past MIN_TRANSCRIPT_BYTES so the reader parses it."""
    filler = "\n" + "x" * (MIN_TRANSCRIPT_BYTES + 16)
    path = directory / name
    path.write_text(body + filler, encoding="utf-8")
    return path


def _healthy_claude_body(text: str = "hello there") -> str:
    return json.dumps({"type": "user", "timestamp": "2026-01-02T03:04:05+00:00", "content": text}) + "\n"


def test_oversized_transcript_is_reported_not_silently_dropped(tmp_path):
    oversized = _write_claude_transcript(tmp_path, "ses_oversized.jsonl", "x" * (MAX_TRANSCRIPT_BYTES + 1))
    good = _write_claude_transcript(tmp_path, "ses_good.jsonl", _healthy_claude_body())
    reader = ClaudeReader(tmp_path)
    sessions = reader.discover()

    reported = {d.session_id: d for d in reader.diagnostics}
    # Readers normalize the 'ses_' file prefix away before reporting.
    assert "oversized" in reported
    assert reported["oversized"].status == STATUS_OVERSIZED
    assert reported["oversized"].size_bytes > MAX_TRANSCRIPT_BYTES
    # Oversized input is skipped, but a healthy session in the same directory still imports.
    assert [s.session_id for s in sessions] == ["good"]
    assert good.exists() and oversized.exists()


def test_malformed_transcript_is_reported(tmp_path):
    _write_claude_transcript(tmp_path, "ses_broken.jsonl", "not json at all\n{oops\n")
    reader = ClaudeReader(tmp_path)
    reader.discover()

    reported = {d.session_id: d for d in reader.diagnostics}
    assert reported["broken"].status == STATUS_MALFORMED
    assert reported["broken"].reason == "no parseable records"
    assert reported["broken"].records_parsed == 0
    # Two bad lines plus the padding line are all unparseable.
    assert reported["broken"].records_malformed == 3


def test_malformed_transcript_does_not_produce_an_empty_session(tmp_path):
    _write_claude_transcript(tmp_path, "ses_broken.jsonl", "not json at all\n{oops\n")
    reader = ClaudeReader(tmp_path)

    # The session is still surfaced so it is not lost, but it is flagged.
    sessions = reader.discover()
    assert len(sessions) == 1
    assert sessions[0].diagnostics.status == STATUS_MALFORMED


def test_codex_oversized_transcript_is_reported(tmp_path):
    (tmp_path / "rollout-huge.jsonl").write_text("y" * (MAX_TRANSCRIPT_BYTES + 10), encoding="utf-8")
    reader = CodexReader(tmp_path)
    reader.discover()

    reported = {d.session_id: d for d in reader.diagnostics}
    assert reported["huge"].status == STATUS_OVERSIZED
    assert reported["huge"].size_bytes > MAX_TRANSCRIPT_BYTES


def test_healthy_session_diagnostics_report_ok(tmp_path):
    _write_claude_transcript(tmp_path, "ses_ok.jsonl", _healthy_claude_body("hello"))
    reader = ClaudeReader(tmp_path)
    sessions = reader.discover()

    assert len(sessions) == 1
    assert sessions[0].diagnostics.status == STATUS_OK
    assert sessions[0].diagnostics.records_parsed == 1
    assert {d.status for d in reader.diagnostics} == {STATUS_OK}


def test_diagnostics_never_contain_the_raw_path(tmp_path):
    _write_claude_transcript(tmp_path, "ses_broken.jsonl", "nope-not-json\n")
    reader = ClaudeReader(tmp_path)
    reader.discover()

    rendered = json.dumps([d.to_dict() for d in reader.diagnostics])
    assert str(tmp_path) not in rendered
    assert "nope" not in rendered


def test_reader_diagnostics_reset_clears_history(tmp_path):
    _write_claude_transcript(tmp_path, "ses_broken.jsonl", "nope-not-json\n")
    reader = ClaudeReader(tmp_path)
    reader.discover()
    assert reader.diagnostics

    reader.reset_diagnostics()
    assert reader.diagnostics == []


def test_readers_expose_diagnostics_attribute(tmp_path):
    for reader in (ClaudeReader(tmp_path), CodexReader(tmp_path)):
        assert hasattr(reader, "diagnostics")
        assert reader.diagnostics == []
        reader.discover()
        assert isinstance(reader.diagnostics, list)
