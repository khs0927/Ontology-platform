from __future__ import annotations

from dataclasses import dataclass

import pytest
from sion_ingestion.advisory_memory import (
    HindsightAdvisoryMemory,
    HindsightConfig,
    bank_id_for_project,
    prepare_advisory_candidates,
)


@dataclass
class Session:
    provider: str = "claude"
    cwd: str = "C:/CODE/private-project"
    created_at: str = "2026-10-02T10:00:00Z"
    decisions: list[str] | None = None
    title: str = "Do not retain this title"
    source_uri: str = "file:///private/transcript.jsonl"
    device_id: str = "private-device"


class FakeClient:
    def __init__(self, *, fail_on: str | None = None):
        self.fail_on = fail_on
        self.retained = []
        self.recalls = []
        self.reflections = []

    def retain(self, **kwargs):
        if self.fail_on and self.fail_on in kwargs["content"]:
            raise RuntimeError("synthetic retain failure")
        self.retained.append(kwargs)
        return {"ok": True}

    def recall(self, **kwargs):
        self.recalls.append(kwargs)
        return {"memories": [{"text": "remembered decision"}]}

    def reflect(self, **kwargs):
        self.reflections.append(kwargs)
        return {"text": "reflection"}


def local_config(**overrides):
    values = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8888",
        "bank_prefix": "sion-project",
        "client_version": "0.10.2",
    }
    values.update(overrides)
    return HindsightConfig(**values)


def test_config_is_disabled_by_default_and_remote_is_fail_closed():
    assert HindsightConfig().enabled is False
    with pytest.raises(ValueError, match="requires https"):
        local_config(base_url="http://memory.example.com", api_key="example-key")
    with pytest.raises(ValueError, match="requires an API key"):
        local_config(base_url="https://memory.example.com", api_key="")
    configured = local_config(base_url="https://memory.example.com", api_key="example-key")
    assert configured.enabled is True


def test_project_banks_are_stable_opaque_and_isolated():
    a1 = bank_id_for_project("private-project")
    a2 = bank_id_for_project("private-project")
    b = bank_id_for_project("other-project")
    assert a1 == a2
    assert a1 != b
    assert "private-project" not in a1


def test_only_explicit_decisions_become_candidates_and_private_paths_are_not_copied():
    sensitive = "api" + "_key=" + "example-sensitive-value"
    batch = prepare_advisory_candidates(
        [Session(decisions=["Use CAIR as canonical truth.", "", sensitive])]
    )
    assert len(batch.candidates) == 1
    assert batch.skipped_empty == 1
    assert batch.skipped_sensitive == 1

    candidate = batch.candidates[0]
    assert candidate.content == "Use CAIR as canonical truth."
    rendered = str(candidate.to_dict())
    assert "transcript.jsonl" not in rendered
    assert "C:/CODE" not in rendered
    assert "private-device" not in rendered
    assert "Do not retain this title" not in rendered
    assert candidate.metadata["canonical"] == "false"
    assert candidate.metadata["memory_role"] == "advisory"


def test_disabled_retain_never_constructs_client():
    called = False

    def factory(_):
        nonlocal called
        called = True
        return FakeClient()

    memory = HindsightAdvisoryMemory(HindsightConfig(enabled=False), client_factory=factory)
    result = memory.retain_sessions([Session(decisions=["Keep this decision"])])
    assert result["status"] == "DISABLED"
    assert result["retained"] == 0
    assert result["canonical_mutation"] is False
    assert called is False


def test_successful_retain_uses_official_shape_and_stays_advisory():
    client = FakeClient()
    memory = HindsightAdvisoryMemory(local_config(), client_factory=lambda _: client)
    result = memory.retain_sessions([Session(decisions=["Prefer adapters over canonical mutation."])])

    assert result["status"] == "SUCCESS"
    assert result["retained"] == 1
    assert result["canonical_mutation"] is False
    assert result["advisory"] is True
    call = client.retained[0]
    assert call["content"] == "Prefer adapters over canonical mutation."
    assert call["context"] == "Sion agent decision; advisory memory only"
    assert call["document_id"].startswith("sion-decision-")
    assert call["bank_id"].startswith("sion-project::")


def test_retain_failures_are_best_effort_and_do_not_raise():
    client = FakeClient(fail_on="fail")
    memory = HindsightAdvisoryMemory(local_config(), client_factory=lambda _: client)
    result = memory.retain_sessions([Session(decisions=["good decision", "this should fail"])])

    assert result["status"] == "PARTIAL"
    assert result["retained"] == 1
    assert len(result["failures"]) == 1
    assert result["canonical_mutation"] is False


def test_recall_is_advisory_and_cannot_update_sion():
    client = FakeClient()
    memory = HindsightAdvisoryMemory(local_config(), client_factory=lambda _: client)
    result = memory.recall("private-project", "What did we decide about CAIR?")

    assert result["status"] == "SUCCESS"
    assert result["canonical"] is False
    assert result["may_update_sion"] is False
    assert result["advisory"] is True
    assert client.recalls[0]["query"] == "What did we decide about CAIR?"
    assert "private-project" not in result["bank_id"]


def test_reflect_is_blocked_by_default_and_opt_in_when_enabled():
    client = FakeClient()
    blocked = HindsightAdvisoryMemory(local_config(), client_factory=lambda _: client)
    result = blocked.reflect("project", "What pattern do you see?")
    assert result["status"] == "BLOCKED"
    assert client.reflections == []

    enabled = HindsightAdvisoryMemory(
        local_config(reflect_enabled=True),
        client_factory=lambda _: client,
    )
    reflected = enabled.reflect("project", "What pattern do you see?")
    assert reflected["status"] == "SUCCESS"
    assert reflected["canonical"] is False
    assert reflected["may_update_sion"] is False
