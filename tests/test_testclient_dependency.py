from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_test_extra_uses_httpx2_and_pyyaml_without_legacy_httpx() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    test_dependencies = project["optional-dependencies"]["test"]

    assert "httpx2==2.13.1" in test_dependencies
    assert "PyYAML==6.0.3" in test_dependencies
    assert not any(dependency.startswith("httpx==") for dependency in test_dependencies)
    assert "httpx2==2.13.1" not in project["dependencies"]


def test_testclient_import_uses_httpx2_without_deprecation_warning() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import warnings; "
                "from starlette.exceptions import StarletteDeprecationWarning; "
                "warnings.simplefilter('error', StarletteDeprecationWarning); "
                "from fastapi.testclient import TestClient; "
                "import starlette.testclient; "
                "assert starlette.testclient.httpx.__name__ == 'httpx2'; "
                "assert TestClient.__mro__[1].__module__.startswith('httpx2')"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
