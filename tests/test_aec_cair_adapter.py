import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sion_ingestion.aec_cair import AecCairAdapter, AecCairConfig, AecCairError


def _adapter(tmp_path: Path) -> AecCairAdapter:
    return AecCairAdapter(AecCairConfig(("aec-mcp",), tmp_path, timeout_seconds=5))


def test_query_global_memory_uses_read_only_mcp_contract(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run(command, *, input, text, capture_output, timeout, check):
        captured["command"] = command
        captured["messages"] = [json.loads(line) for line in input.splitlines() if line]
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "structuredContent": {
                    "route": "GLOBAL_MEMORY",
                    "query": "door",
                    "hits": [{"project_id": "P1", "object_id": "aec://object/1", "score": 1.0}],
                }
            },
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n" + json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr("sion_ingestion.aec_cair.subprocess.run", fake_run)
    result = _adapter(tmp_path).query_global_memory("door", top_k=3, project_id="P1")

    assert result["route"] == "GLOBAL_MEMORY"
    assert captured["command"][-2:] == ["--root", str(tmp_path)]
    call = next(message for message in captured["messages"] if message.get("id") == 2)
    assert call["params"]["name"] == "aec.query_global_memory"
    assert call["params"]["arguments"] == {"question": "door", "top_k": 3, "project_id": "P1"}


def test_adapter_rejects_mutating_or_unapproved_tools(tmp_path: Path):
    with pytest.raises(AecCairError, match="not allowed"):
        _adapter(tmp_path).call("aec.graph_hydradb_export", {})


def test_adapter_requires_existing_ontology_root(tmp_path: Path):
    missing = tmp_path / "missing"
    adapter = AecCairAdapter(AecCairConfig(("aec-mcp",), missing))
    with pytest.raises(AecCairError, match="root not found"):
        adapter.query_global_memory("wall")


def test_adapter_surfaces_tool_failures(tmp_path: Path, monkeypatch):
    def fake_run(*args, **kwargs):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"structuredContent": {"status": "FAILED", "error": "boom"}},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr("sion_ingestion.aec_cair.subprocess.run", fake_run)
    with pytest.raises(AecCairError, match="boom"):
        _adapter(tmp_path).get_object("aec://object/1")


@pytest.mark.parametrize("duplicate", [False, True])
def test_adapter_rejects_error_and_duplicate_tool_results(tmp_path: Path, monkeypatch, duplicate):
    payload = {"jsonrpc": "2.0", "id": 2, "result": {
        "isError": not duplicate, "structuredContent": {"status": "OK"}}}
    stdout = json.dumps(payload) + "\n"
    if duplicate:
        stdout += json.dumps(payload) + "\n"
    monkeypatch.setattr("sion_ingestion.aec_cair.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    with pytest.raises(AecCairError, match="duplicate|error tool result"):
        _adapter(tmp_path).get_object("aec://object/1")
