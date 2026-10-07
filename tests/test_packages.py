"""Monorepo package layout, lazy imports and optional-extra helpers."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sion_core import EXTRAS, MissingExtra, extras_report, is_available, require

HEAVY = ("ezdxf", "ifcopenshell", "lightrag", "googleapiclient")


def test_core_import_does_not_load_optional_extras():
    code = (
        "import json, sys\n"
        "import sion_api.main, sion_ingestion, sion_cad, sion_bim, sion_cair, sion_drive_store, sion_graphrag\n"
        f"print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_legacy_module_paths_alias_new_packages():
    import sion_bim.ifc
    import sion_cad.dxf
    import sion_cair.adapter
    from sion_ingestion import aec_cair, dxf_ingest, ifc_ingest

    assert dxf_ingest is sion_cad.dxf
    assert ifc_ingest is sion_bim.ifc
    assert aec_cair is sion_cair.adapter


def test_sion_ingestion_lazy_exports():
    import sion_ingestion

    assert sion_ingestion.AecCairAdapter.__module__ == "sion_cair.adapter"
    assert callable(sion_ingestion.import_map_export)
    with pytest.raises(AttributeError):
        sion_ingestion.does_not_exist  # noqa: B018


def test_require_names_the_extra():
    with pytest.raises(MissingExtra) as info:
        require("definitely_not_installed_sion_module", extra="cad")
    assert "sion-ontology-platform[cad]" in str(info.value)
    assert require("json").dumps({}) == "{}"
    assert is_available("json")
    assert not is_available("definitely_not_installed_sion_module")


def test_extras_report_matches_registry():
    report = extras_report()
    assert set(report) == set(EXTRAS) == {"cad", "bim", "rag", "drive"}
    for extra, info in report.items():
        assert info["installed"] == (not info["missing"])
        assert info["installed"] == all(is_available(m) for m in EXTRAS[extra])


def test_extras_endpoint(tmp_path):
    from sion_api.main import create_app

    app = create_app(database_url=f"sqlite:///{tmp_path / 'x.db'}")
    with TestClient(app) as client:
        body = client.get("/api/v1/system/extras").json()
    assert set(body["extras"]) == {"cad", "bim", "rag", "drive"}
    assert body["version"]
