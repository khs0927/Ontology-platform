from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_NAMES = (
    "sion-core.yaml",
    "sion-core.shacl.ttl",
    "current-map-inventory.json",
    "map-export.example.json",
)
COMMAND_TIMEOUT_SECONDS = 300


def _clean_environment(venv_root: Path, isolated_cwd: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith(("PIP_", "SION_")):
            environment.pop(name)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["VIRTUAL_ENV"] = str(venv_root)
    scripts = venv_root / ("Scripts" if os.name == "nt" else "bin")
    environment["PATH"] = os.pathsep.join(
        [str(scripts), environment.get("PATH", "")]
    ).rstrip(os.pathsep)
    isolated_cwd.mkdir(parents=True, exist_ok=True)
    return environment


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"packaging blocker: could not run {command!r}: {exc}")
    if result.returncode != 0:
        pytest.fail(
            "packaging blocker: command failed with "
            f"exit {result.returncode}: {command!r}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _python(venv_root: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return venv_root / relative


def _console_script(venv_root: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / f"{name}.exe"
    return venv_root / "bin" / name


def _create_venv(path: Path) -> None:
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(path)
    except OSError as exc:
        pytest.fail(f"packaging blocker: could not create isolated venv at {path}: {exc}")


def _pip_install(
    target: str | Path,
    *,
    venv_root: Path,
    cwd: Path,
    environment: dict[str, str],
    editable: bool = False,
) -> None:
    _run(
        [
            str(_python(venv_root)),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            *(["--editable"] if editable else []),
            str(target),
        ],
        cwd=cwd,
        environment=environment,
    )


def _build_one(kind: str, builder: Path, output: Path, sandbox: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    environment = _clean_environment(builder, sandbox)
    _run(
        [str(_python(builder)), "-m", "build", f"--{kind}", "--outdir", str(output), str(ROOT)],
        cwd=sandbox,
        environment=environment,
    )
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    artifacts = list(output.glob(f"*{suffix}"))
    if len(artifacts) != 1:
        pytest.fail(
            "packaging blocker: expected exactly one freshly built "
            f"{kind} in {output}, found {sorted(path.name for path in artifacts)}"
        )
    return artifacts[0]


def _verify_clean_runtime(venv_root: Path, label: str, sandbox: Path) -> dict[str, str]:
    environment = _clean_environment(venv_root, sandbox)
    _run(
        [str(_console_script(venv_root, "sion-agent-bridge")), "--help"],
        cwd=sandbox,
        environment=environment,
    )
    _run(
        [str(_console_script(venv_root, "alembic")), "--help"],
        cwd=sandbox,
        environment=environment,
    )
    script = r"""
import hashlib
import importlib.metadata
import importlib.resources
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sion_api.main import create_app

assert callable(command.upgrade)
assert Config is not None

module_path = Path(importlib.resources.files("sion_api.main")).resolve()
resource_hashes = {}
for name in (
    "sion-core.yaml",
    "sion-core.shacl.ttl",
    "current-map-inventory.json",
    "map-export.example.json",
):
    resource = importlib.resources.files("sion_api.resources").joinpath(name)
    payload = resource.read_bytes()
    resource_hashes[name] = hashlib.sha256(payload).hexdigest()

app = create_app(database_url="sqlite+pysqlite:///:memory:")
assert callable(app)

print(json.dumps({
    "module_path": str(module_path),
    "resource_hashes": resource_hashes,
    "version": importlib.metadata.version("sion-ontology-platform"),
}))
"""
    result = _run(
        [str(_python(venv_root)), "-I", "-c", script],
        cwd=sandbox,
        environment=environment,
    )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        pytest.fail(f"packaging blocker: {label} runtime probe returned invalid JSON: {exc}")

    module_path = Path(payload["module_path"]).resolve()
    if label in {"wheel", "sdist"} and ROOT in module_path.parents:
        pytest.fail(
            f"packaging blocker: {label} clean install imported from checkout/source path {module_path}"
        )
    if label == "editable" and ROOT not in module_path.parents:
        pytest.fail(
            f"packaging blocker: editable install did not import from the checkout: {module_path}"
        )

    return payload["resource_hashes"]


def _verify_test_client_smoke(venv_root: Path, sandbox: Path) -> None:
    environment = _clean_environment(venv_root, sandbox)
    script = r"""
from fastapi.testclient import TestClient
from sion_api.main import create_app

with TestClient(create_app(database_url="sqlite+pysqlite:///:memory:")) as client:
    response = client.get("/health/live")
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "ok", body
print(body)
"""
    _run([str(_python(venv_root)), "-I", "-c", script], cwd=sandbox, environment=environment)


def test_fresh_artifacts_clean_install_and_resource_hash_parity(tmp_path: Path) -> None:
    """Build, install, and smoke-test artifacts without reusing repo state."""
    builder = tmp_path / "builder-venv"
    sandbox = tmp_path / "builder-cwd"
    _create_venv(builder)
    builder_environment = _clean_environment(builder, sandbox)
    _run(
        [str(_python(builder)), "-m", "pip", "install", "--no-cache-dir", "build>=1.2"],
        cwd=sandbox,
        environment=builder_environment,
    )

    wheel = _build_one("wheel", builder, tmp_path / "wheel-dist", sandbox)
    sdist = _build_one("sdist", builder, tmp_path / "sdist-dist", sandbox)

    hashes: dict[str, dict[str, str]] = {}
    for label, artifact in (("wheel", wheel), ("sdist", sdist), ("editable", ROOT)):
        runtime = tmp_path / f"{label}-venv"
        runtime_sandbox = tmp_path / f"{label}-cwd"
        _create_venv(runtime)
        environment = _clean_environment(runtime, runtime_sandbox)
        _pip_install(
            artifact,
            venv_root=runtime,
            cwd=runtime_sandbox,
            environment=environment,
            editable=(label == "editable"),
        )
        hashes[label] = _verify_clean_runtime(runtime, label, runtime_sandbox)

        test_runtime = tmp_path / f"{label}-test-venv"
        test_sandbox = tmp_path / f"{label}-test-cwd"
        _create_venv(test_runtime)
        test_environment = _clean_environment(test_runtime, test_sandbox)
        _pip_install(
            f"{artifact}[test]",
            venv_root=test_runtime,
            cwd=test_sandbox,
            environment=test_environment,
            editable=(label == "editable"),
        )
        _verify_test_client_smoke(test_runtime, test_sandbox)

    reference = hashes["editable"]
    for label in ("wheel", "sdist"):
        assert hashes[label] == reference, (
            f"packaging blocker: {label} resource hashes differ from editable: "
            f"wheel/sdist={hashes[label]!r}, editable={reference!r}"
        )
