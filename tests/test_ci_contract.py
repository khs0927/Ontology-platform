from pathlib import Path
import re
import tomllib

import pytest

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED_JOBS = {
    "pytest-suite",
    "alembic-revision-contract",
    "postgres-core",
    "postgres-pgvector",
    "resource-wheel-contract",
    "secret-scan",
}
POSTGRES_JOBS = {"postgres-core", "postgres-pgvector"}


def _test_extra_declares_pyyaml() -> bool:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return any(
        dependency.lower().replace("_", "-").startswith("pyyaml")
        for dependency in pyproject["project"]["optional-dependencies"]["test"]
    )


PYYAML_DECLARED = _test_extra_declares_pyyaml()
YAML_BLOCKER = (
    "BLOCKER: PyYAML is not declared in the test extra, so YAML-level "
    "CI contracts cannot run after `pip install -e .[test]`"
    if not PYYAML_DECLARED
    else "BLOCKER: PyYAML is declared in the test extra but is unavailable in the active environment"
)


def _workflow() -> dict:
    if yaml is None:
        pytest.skip(YAML_BLOCKER)
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("jobs")
    return data


def _commands(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_ci_workflow_is_valid_yaml():
    _workflow()


def test_required_jobs_and_actual_commands_match_contract():
    data = _workflow()
    assert REQUIRED_JOBS <= set(data["jobs"])
    commands = "\n".join(_commands(job) for job in data["jobs"].values())
    for name in (
        "test_auth.py",
        "test_dlp.py",
        "test_evidence_contract.py",
        "test_bridge_upsert.py",
        "test_sync_atomic.py",
        "test_automation_security.py",
        "test_frozen_contract.py",
        "test_alembic_contract.py",
        "test_resource_package.py",
    ):
        assert name in commands
    assert "python -m pytest" in commands


def test_postgres_jobs_use_application_database_contract_and_real_migrations():
    data = _workflow()
    for name in POSTGRES_JOBS:
        job = data["jobs"][name]
        env = job["env"]
        assert env["SION_DATABASE_URL"].startswith("postgresql+psycopg://")
        assert str(env["SION_ALEMBIC_EXECUTE_SCHEMA_CREATE"]) == "1"
        assert "DATABASE_URL" not in env
        commands = _commands(job)
        assert "alembic upgrade head" in commands
        assert "alembic current" in commands
        assert "alembic heads" in commands
        assert 'os.environ["SION_DATABASE_URL"]' in commands
        assert 'result["status"] == "ready"' in commands


def test_postgres_core_and_pgvector_scopes_are_separate():
    data = _workflow()
    core = data["jobs"]["postgres-core"]
    vector = data["jobs"]["postgres-pgvector"]
    core_commands = _commands(core)
    vector_commands = _commands(vector)

    assert "vector_enabled=False" in core_commands
    assert "tests/test_readiness.py" in core_commands
    assert "test_vector_readiness.py" not in core_commands
    assert "vector_enabled=True" not in core_commands

    assert vector["env"]["SION_VECTOR_ENABLED"] == "1"
    assert "vector_enabled=True" in vector_commands
    assert "tests/test_vector_readiness.py" in vector_commands
    assert "tests/test_readiness.py" not in vector_commands
    assert "vector_enabled=False" not in vector_commands


def test_ci_security_permissions_pins_timeouts_and_billing_fail_closed():
    data = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")

    assert data["permissions"] == {"contents": "read"}
    assert data["concurrency"]["cancel-in-progress"] is True
    assert all(job.get("timeout-minutes") for job in data["jobs"].values())

    action_refs = re.findall(r"^\s*uses:\s*([^\s]+)\s*$", text, re.MULTILINE)
    assert action_refs
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref) for ref in action_refs)

    assert text.count("pgvector/pgvector:0.8.6-pg16") == 2
    assert "if: always()" not in text
    assert "success()" not in text
    assert "continue-on-error: true" not in text
    assert "uses: ./.github/workflows/ci.yml" not in text


def test_pyyaml_test_extra_blocker_is_explicit():
    source = Path(__file__).read_text(encoding="utf-8")
    assert "PyYAML is not declared in the test extra" in source
    if yaml is None:
        assert PYYAML_DECLARED, YAML_BLOCKER


def test_new_contract_files_exist():
    assert WORKFLOW.is_file()
    assert (ROOT / "docs" / "RELEASE_CHECKLIST.md").is_file()
    assert (ROOT / "tests" / "test_ci_contract.py").is_file()
