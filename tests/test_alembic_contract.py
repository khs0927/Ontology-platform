from __future__ import annotations

import ast
import configparser
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_alembic_contract_files_and_configuration() -> None:
    assert "alembic==1.17.1" in (ROOT / "pyproject.toml").read_text()
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / "alembic.ini")
    assert config.get("alembic", "script_location") == "%(here)s/migrations"
    assert (ROOT / "migrations/env.py").is_file()
    assert (ROOT / "migrations/script.py.mako").is_file()


def test_baseline_is_a_stamp_first_contract() -> None:
    source = (ROOT / "migrations/versions/0001_baseline.py").read_text()
    tree = ast.parse(source)
    assert any(isinstance(node, ast.FunctionDef) and node.name == "baseline_stamp" for node in tree.body)
    assert "op.execute" not in source
    assert "raw SQL" not in source
    assert "SION_ALEMBIC_EXECUTE_SCHEMA_CREATE" in source
    assert "raise NotImplementedError" in source
