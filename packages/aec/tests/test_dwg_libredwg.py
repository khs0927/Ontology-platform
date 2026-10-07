from pathlib import Path
import shutil

import pytest

from aec_intelligence.dwg import LibreDWGConverter, ODAConverter, select_dwg_converter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "simple_house.dwg"
# Binary fixtures are not committed in the Sion monorepo (packages/aec was imported without
# binaries). Tests that need the real DWG skip; the rest use a stub file.
needs_fixture = pytest.mark.skipif(not FIXTURE.is_file(), reason="binary DWG fixture not in the monorepo")


def _stub_dwg(tmp_path: Path) -> Path:
    stub = tmp_path / "stub.dwg"
    stub.write_bytes(b"AC1032" + b"\x00" * 26)
    return stub


def test_select_converter_modes(monkeypatch):
    monkeypatch.setattr("aec_intelligence.dwg.shutil.which", lambda name: "/usr/bin/dwg2dxf" if name == "dwg2dxf" else None)
    assert isinstance(select_dwg_converter("auto"), LibreDWGConverter)
    assert isinstance(select_dwg_converter("auto", oda_executable="/x/ODAFileConverter"), ODAConverter)
    assert isinstance(select_dwg_converter("oda"), ODAConverter)
    with pytest.raises(ValueError):
        select_dwg_converter("bogus")


def test_libredwg_reports_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setattr("aec_intelligence.dwg.shutil.which", lambda name: None)
    result = LibreDWGConverter().convert_to_dxf(_stub_dwg(tmp_path), tmp_path / "out")
    assert result.status == "FAILED"
    assert "not configured" in result.errors[0]


@needs_fixture
@pytest.mark.skipif(shutil.which("dwg2dxf") is None, reason="LibreDWG dwg2dxf not installed")
def test_libredwg_converts_fixture_readable_by_ezdxf(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    before = FIXTURE.read_bytes()
    result = LibreDWGConverter().convert_to_dxf(FIXTURE, tmp_path)
    assert result.status == "SUCCESS", result.checks
    document = ezdxf.readfile(result.output)
    types = {entity.dxftype() for entity in document.modelspace()}
    assert {"LINE", "TEXT"} <= types
    assert FIXTURE.read_bytes() == before
