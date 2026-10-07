"""Phase 4: one DXF reading path (sion_cad.reader) for Sion ingest, GOD-CAD and aec_intelligence."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_cad import reader

ROOT = Path(__file__).resolve().parents[1]
SIMPLE = ROOT / "packages" / "aec" / "fixtures" / "simple_house.dxf"
KO_DIR = ROOT / "packages" / "aec" / "tests" / "fixtures" / "drawings_ko"
CP949 = KO_DIR / "A-102_2층평면도_cp949.dxf"

needs_ezdxf = pytest.mark.skipif(not reader.ezdxf_available(), reason="needs the 'cad' extra")


def _norm(items):
    return [(i["kind"], i["name"], i["layer"]) for i in items]


@pytest.mark.parametrize("path", [SIMPLE, *sorted(KO_DIR.glob("*.dxf"))], ids=lambda p: p.name)
def test_fallback_parser_matches_ezdxf(path: Path):
    fallback = reader.read_entities(path, prefer_ezdxf=False)
    assert fallback.parser == "text-fallback"
    assert fallback.items
    if reader.ezdxf_available():
        primary = reader.read_entities(path)
        assert primary.parser == "ezdxf"
        assert _norm(primary.items) == _norm(fallback.items)


def test_korean_legacy_drawing_text_is_decoded():
    names = {i["name"] for i in reader.read_entities(CP949).items if i["kind"] == "annotation"}
    assert {"거실", "침실1", "주방"} <= names


@needs_ezdxf
def test_open_dxf_recovers_damaged_file(tmp_path: Path):
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("RECOVER ME", dxfattribs={"layer": "A-ANNO"})
    good = tmp_path / "good.dxf"
    doc.saveas(good)
    damaged = tmp_path / "damaged.dxf"
    text = good.read_text(encoding="utf-8")
    # drop the CLASSES/TABLES structure markers so the strict reader fails
    damaged.write_text(text.replace("TABLES", "TABLEZ", 1), encoding="utf-8")
    loaded, warnings = reader.open_dxf(damaged)
    assert any("recovered with ezdxf.recover" in w for w in warnings) or warnings == []
    assert [e.dxf.text for e in loaded.modelspace() if e.dxftype() == "TEXT"] == ["RECOVER ME"]


def test_reader_without_ezdxf_raises_runtime_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(reader, "_ezdxf", lambda: None)
    with pytest.raises(reader.DxfReaderUnavailable):
        reader.open_dxf(SIMPLE)
    assert issubclass(reader.DxfReaderUnavailable, RuntimeError)
    assert reader.read_entities(SIMPLE).parser == "text-fallback"


def test_all_consumers_share_the_reader():
    aec_dxf = pytest.importorskip("aec_intelligence.dxf")
    assert aec_dxf.read_dxf is reader.open_dxf
    assert aec_dxf.decode_dxf_text is reader.decode_dxf_text
    god_dxf = pytest.importorskip("god_cad.adapters.dxf") if reader.ezdxf_available() else None
    if god_dxf is not None:
        assert god_dxf.open_dxf is reader.open_dxf
        assert "ezdxf.readfile" not in inspect.getsource(god_dxf)
    import sion_cad.dxf

    assert "ezdxf.readfile" not in inspect.getsource(sion_cad.dxf)


def test_sion_cad_import_is_light():
    import subprocess
    import sys

    code = "import sys, sion_cad.reader; print('sqlalchemy' in sys.modules, 'ezdxf' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False", "False"]


@needs_ezdxf
def test_god_cad_analysis_endpoint(tmp_path: Path):
    pytest.importorskip("god_cad")
    import ezdxf
    from sion_api.main import create_app

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": "WAL1"})
    msp.add_line((1000, 0), (1000, 1000), dxfattribs={"layer": "WAL1"})
    msp.add_circle((500, 500), 150, dxfattribs={"layer": "COL"})
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    app = create_app(database_url="sqlite://", auto_create_schema=True, ingest_roots=[tmp_path])
    with TestClient(app) as c:
        r = c.post("/api/v1/analyze/dxf", json={"path": str(path), "drawing_id": "test-plan"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["analysis_engine"] == "god-cad"
        assert body["drawing_id"] == "test-plan"
        assert len(body["entities"]) == 3
        classes = {o["class_uri"] for o in body["semantic_objects"]}
        assert {"https://w3id.org/beo#Wall", "https://w3id.org/beo#Column"} <= classes
        assert body["edges"]  # endpoint topology between the two wall lines
        bad = c.post("/api/v1/analyze/dxf", json={"path": str(path), "units": "furlong"})
        assert bad.status_code == 422
        outside = c.post("/api/v1/analyze/dxf", json={"path": str(SIMPLE)})
        assert outside.status_code in {403, 422}


def test_bundled_cair_config(monkeypatch):
    from sion_cair.adapter import AecCairConfig, bundled_root

    monkeypatch.setenv("SION_AEC_ONTOLOGY_ROOT", "bundled")
    monkeypatch.delenv("SION_AEC_MCP_COMMAND", raising=False)
    config = AecCairConfig.from_env()
    assert config.repository_root == bundled_root().resolve()
    assert config.command[1:] == ("-m", "aec_intelligence.mcp_stdio")
    assert (bundled_root() / "src" / "aec_intelligence").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="stdio subprocess timing on Windows runners")
def test_bundled_cair_live_read_only_call(monkeypatch):
    pytest.importorskip("aec_intelligence.mcp_stdio")
    from sion_cair.adapter import AecCairAdapter, AecCairConfig, AecCairError

    monkeypatch.setenv("SION_AEC_ONTOLOGY_ROOT", "bundled")
    monkeypatch.delenv("SION_AEC_MCP_COMMAND", raising=False)
    adapter = AecCairAdapter(AecCairConfig.from_env())
    assert adapter.enabled
    result = adapter.call("aec.graph_backend_plan", {})
    assert isinstance(result, dict)
    with pytest.raises(AecCairError):
        adapter.call("aec.write_anything", {})
