"""scripts/run_agent_bridge.py exposes every documented reader (PR #41 review)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("run_agent_bridge_cli", ROOT / "scripts" / "run_agent_bridge.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_expands_to_every_registered_reader(cli):
    from sion_ingestion.agent_bridge import PROVIDER_REGISTRY

    providers = cli.resolve_providers("all")
    assert {"deepseek", "hermes", "zcode"} <= set(providers)
    assert set(providers) == set(PROVIDER_REGISTRY)
    assert providers[:3] == ["antigravity", "codex", "claude"]


@pytest.mark.parametrize("name", ["deepseek", "hermes", "zcode"])
def test_new_readers_are_selectable(cli, name):
    args = cli.build_parser().parse_args(["--provider", name])
    assert cli.resolve_providers(args.provider) == [name]


def test_documented_root_override_is_discovered_through_the_cli(cli, tmp_path, monkeypatch, capsys):
    (tmp_path / "s.jsonl").write_text('{"role":"user","content":"bridge check"}\n', encoding="utf-8")
    monkeypatch.setenv("SION_ZCODE_ROOT", str(tmp_path))
    for env in ("SION_DEEPSEEK_ROOT", "SION_HERMES_ROOT"):
        monkeypatch.setenv(env, str(tmp_path / "missing"))
    args = SimpleNamespace(export_out=str(tmp_path / "e.json"), pg_out=str(tmp_path / "p.sql"),
                           graph_out=str(tmp_path / "g.md"), dry_run=True)
    cli.sync_cycle(args, ["deepseek", "hermes", "zcode"], None)
    out = capsys.readouterr().out
    assert "zcode: discovered 1 session(s)" in out
    assert (tmp_path / "e.json").exists()
