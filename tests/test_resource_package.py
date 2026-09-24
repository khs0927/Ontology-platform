from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_NAMES = {
    "sion-core.yaml",
    "sion-core.shacl.ttl",
    "current-map-inventory.json",
    "map-export.example.json",
}


def test_resource_resolver_and_explicit_overrides(monkeypatch, tmp_path):
    from sion_api.config import load_settings
    from sion_api.resources import resource_path

    assert resource_path("sion-core.yaml").is_file()
    assert resource_path("sion-core.shacl.ttl").is_file()
    assert resource_path("current-map-inventory.json").is_file()
    assert resource_path("map-export.example.json").is_file()

    ontology = tmp_path / "ontology.yaml"
    inventory = tmp_path / "inventory.json"
    monkeypatch.setenv("SION_ONTOLOGY_PATH", str(ontology))
    monkeypatch.setenv("SION_MAP_INVENTORY_PATH", str(inventory))
    settings = load_settings()
    assert settings.ontology_path == ontology
    assert settings.map_inventory_path == inventory


def test_wheel_contains_resources_and_entry_point():
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", directory, str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        wheel = next(Path(directory).glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            assert all(f"sion_api/resources/{name}" in names for name in RESOURCE_NAMES)
            entry_points = next(
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            )
            text = archive.read(entry_points).decode()
            assert "sion-agent-bridge = sion_ingestion.bridge_cli:main" in text
