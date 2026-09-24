from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_exe.py"
SPEC = ROOT / "sion-agent-bridge.spec"


def test_build_script_has_runtime_data_root_contract() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    validator = functions["_validate_runtime_data_root"]
    calls = set()
    for node in ast.walk(validator):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    assert "expanduser" in calls
    assert "resolve" in calls
    assert "mkdir" in calls
    assert "SION_DATA_ROOT" in source
    assert "_MEIPASS" in source
    assert "sys._MEIPASS" not in source


def test_manifest_records_runtime_versions_commit_and_frozen_data_root(tmp_path: Path) -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert 'metadata.version("pyinstaller")' in source
    assert "platform.python_version()" in source
    assert '"commit": _git("rev-parse", "HEAD")' in source
    assert '"SION_DATA_ROOT": str(data_root)' in source
    assert "frozen bridge reads SION_DATA_ROOT at runtime" in source


def test_manifest_is_serializable_with_real_tool_versions(tmp_path: Path) -> None:
    try:
        importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("PyInstaller is not installed in this test environment")
    import importlib.util as importlib_util
    spec = importlib_util.spec_from_file_location("build_exe", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module._manifest(tmp_path)
    assert manifest["python"]
    assert manifest["pyinstaller"]
    assert manifest["commit"]


def test_build_script_records_version_and_commit_and_upx_is_explicit() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    manifest = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_manifest"
    )
    manifest_source = ast.get_source_segment(source, manifest) or ""
    assert "describe" in manifest_source
    assert "rev-parse" in manifest_source
    assert "build-manifest.json" in source
    assert "spec's explicit upx=False" in source
    assert "--upx/--noupx" in source


def test_spec_normalizes_resource_destination_and_uses_qualified_hidden_imports() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'Path("sion_api") / "resources"' in source
    assert 'p.relative_to(API_ROOT / "sion_api" / "resources")' in source
    assert '"sion_ingestion.bridge_cli"' in source
    assert '"bridge_cli"' not in source
    assert "datas=datas" in source
    assert "upx=False" in source


def test_pyinstaller_archive_dry_inspection_is_reproducible() -> None:
    """The rehearsal artifact is dist, never the committed bin executable."""
    exe = ROOT / "dist" / "sion-agent-bridge.exe"
    if not exe.is_file() or not os.environ.get("SION_TEST_PYINSTALLER_ARCHIVE"):
        return
    completed = subprocess.run(
        [sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer", "--list", str(exe)],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    archive = completed.stdout
    assert "sion_api" in archive and "resources" in archive
    assert "sion-core.yaml" in archive
    assert "sion-core.shacl.ttl" in archive
    assert "current-map-inventory.json" in archive
    assert "map-export.example.json" in archive
    # PYZ members are not expanded by --list; the executable help check below
    # exercises the qualified bridge_cli entry point in the frozen runtime.


def test_frozen_rehearsal_targets_dist_not_bin() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert 'DIST_DIR = REPO_ROOT / "dist"' in source
    assert 'ROOT / "bin"' not in source


def test_frozen_exe_help_exercises_qualified_entrypoint() -> None:
    exe = ROOT / "dist" / "sion-agent-bridge.exe"
    if not exe.is_file() or not os.environ.get("SION_TEST_PYINSTALLER_ARCHIVE"):
        return
    completed = subprocess.run([str(exe), "--help"], text=True, capture_output=True)
    assert completed.returncode == 0
    assert "--provider" in completed.stdout
