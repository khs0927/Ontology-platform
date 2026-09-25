from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
VALIDATOR = ROOT / "scripts" / "validate-workflows.ps1"
ACTION_PIN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # PyYAML 6 implements YAML 1.1, where the unquoted key `on` becomes True.
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    return data


def test_validator_is_repository_scoped_and_fail_closed_by_default() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    assert "https://github.com/rhysd/actionlint/releases/download/" in text
    assert "Get-FileHash" in text and "SHA-256 mismatch" in text
    assert "[IO.Path]::GetTempPath()" in text
    assert "AllowContractFallback" in text
    assert "actionlint failed" in text and "PyYAML/contract fallback failed" in text


def test_workflow_parses_and_satisfies_security_contract() -> None:
    data = _workflow()
    assert data["permissions"] == {"contents": "read"}
    assert data["concurrency"]["cancel-in-progress"] is True
    assert isinstance(data["jobs"], dict) and data["jobs"]

    names = set(data["jobs"])
    for name, job in data["jobs"].items():
        assert job.get("timeout-minutes"), name
        assert isinstance(job.get("steps"), list) and job["steps"], name
        for need in job.get("needs", []):
            assert need in names, f"{name} needs unknown job {need}"
        for step in job["steps"]:
            assert ("uses" in step) != ("run" in step), (name, step)
            if "uses" in step:
                assert ACTION_PIN.fullmatch(step["uses"]), step["uses"]
            else:
                assert step.get("shell") == "bash", (name, step)
        for service in (job.get("services") or {}).values():
            assert service.get("image")
            assert "health-cmd" in service.get("options", "")


def test_expressions_and_environment_are_scoped() -> None:
    data = _workflow()
    for name, job in data["jobs"].items():
        assert isinstance(job.get("env", {}), dict), name
    raw = WORKFLOW.read_text(encoding="utf-8")

    assert raw.count("${{") == raw.count("}}")
    assert "github.event.pull_request.head.repo" not in raw


def test_windows_validator_passes_explicit_shell_workflow() -> None:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh is unavailable; actionlint is exercised in Windows preflight")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(VALIDATOR), "-WorkflowPath", str(WORKFLOW)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
