"""Parser for the official NVIDIA SQL-result envelope. No network and no secrets."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "nvidia-auto-ontology"
    / "ci"
    / "official_live_pipeline.py"
)


def _pipeline():
    spec = importlib.util.spec_from_file_location("official_live_pipeline", _MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("official live pipeline module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decodes_upstream_json_string_envelope():
    # Shape captured by NVIDIA's own MCP client: a one-item list of JSON records.
    pipeline = _pipeline()
    assert pipeline.executed_aggregate(['[{"count": 2}]']) == 2
    assert pipeline.executed_aggregate(['[{"CUSTOMER_COUNT": "2"}]']) == 2
    assert pipeline.executed_aggregate([{"count": 2.0}]) == 2


def test_wrong_aggregate_stays_visible():
    pipeline = _pipeline()
    assert pipeline.executed_aggregate(['[{"count": 1}]']) == 1
    assert pipeline.executed_aggregate(['[{"count": 0}]']) == 0


def test_row_dump_is_not_an_aggregate():
    pipeline = _pipeline()
    rows = ['[{"object_name": "Door-101"}, {"object_name": "Door-102"}]']
    with pytest.raises(ValueError, match="not a single integer aggregate"):
        pipeline.executed_aggregate(rows)
    with pytest.raises(ValueError, match="not a single integer aggregate"):
        pipeline.executed_aggregate(["[]"])
    with pytest.raises(ValueError, match="not a single integer aggregate"):
        pipeline.executed_aggregate([{"ready": True}])
    with pytest.raises(ValueError, match="not JSON"):
        pipeline.executed_aggregate(["not-json"])
