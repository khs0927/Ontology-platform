"""Drawing number / category from plain title-block text when the file name carries no metadata.

All fixtures are synthetic; file names are hash-like so the file-name fallback cannot answer.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from aec_intelligence.classifier import drawing_category
from aec_intelligence.operational.parsers import pick_sheet_number, sheet_number_text


@pytest.mark.parametrize("text, expected", [
    ("A-101", ("A-101", True)),
    ("C - 010", ("C-010", True)),
    ("S- 101", ("S-101", True)),
    ("MC - 008", ("MC-008", True)),
    ("AR-1001", ("AR-1001", True)),
    ("A-101-1", ("A-101-1", True)),
    ("a101", ("A-101", False)),
    ("건축-01", ("건축-01", True)),
    ("건축 - 12", ("건축-12", True)),
    ("건축01", None),
    ("A-1", None),
    ("C1", None),
    ("2층 평면도", None),
    ("A-101 평면도", None),
    ("SCALE 1/100", None),
])
def test_sheet_number_text(text, expected):
    assert sheet_number_text(text) == expected


def _cand(value, layer="0", dash=True, center=(0.0, 0.0), height=3.0):
    return {"value": value, "dash": dash, "height": height, "center": center, "layer": layer}


def test_pick_prefers_label_then_sheet_layer_and_rejects_plain_marks():
    label = [{"center": (0.0, 10.0), "height": 3.0}]
    assert pick_sheet_number([_cand("WD-01", center=(500.0, 500.0)), _cand("A-102", center=(5.0, 5.0))], label)[0] == "A-102"
    assert pick_sheet_number([_cand("T-18", layer="SH")], [])[:2] == ("T-18", "sheet_layer")
    assert pick_sheet_number([_cand("M-503", layer="x. 출력")], [])[0] == "M-503"
    # A dashed mark on an ordinary layer with no label nearby is not a sheet number.
    assert pick_sheet_number([_cand("SD-01", layer="A-DOOR")], []) is None
    # An undashed code needs a label.
    assert pick_sheet_number([_cand("A-101", layer="SH", dash=False)], []) is None
    assert pick_sheet_number([_cand("A-101", dash=False, center=(1.0, 9.0))], label)[0] == "A-101"


def test_pick_reports_all_top_candidates():
    picked = pick_sheet_number([_cand("E-17", "SH", height=5), _cand("E-18", "SH", height=3)], [])
    assert picked[0] == "E-17" and picked[2] == ["E-17", "E-18"]


@pytest.mark.parametrize("text, expected", [
    ("지상3층 메인화장실 확대 환기덕트 평면도", "평면도"),
    ("ENLARGED FLOOR PLAN", "평면도"),
    ("화장실 확대 상세도", "상세도"),
    ("면벽식옹벽 구조도", "구조도"),
    ("구조 시방서 -1", "시방서"),
    ("GENERAL SPECIFICATIONS", "시방서"),
    ("지하 2층 구조평면도", "구조평면도"),
    ("계단 상세도", "상세도"),
])
def test_drawing_category_new_rules(text, expected):
    assert drawing_category(("text", text))["drawing_category"] == expected


ezdxf = pytest.importorskip("ezdxf")


def _settings(root: Path):
    return types.SimpleNamespace(data_root=root, oda_executable="", libredwg_executable="", dwg_converter="auto")


def _parse(tmp_path: Path, doc):
    from aec_intelligence.operational.parsers import parse_source

    source = tmp_path / "3f9a0c2d71e4b5a6.dxf"
    doc.saveas(source)
    result = parse_source(source, "doc_neutral", tmp_path / "out", _settings(tmp_path))
    return {o["evidence"]["layout"]: o for o in result["objects"] if o["type"] == "View"}


def test_neutral_file_takes_number_from_sheet_layer_text(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("SH")
    msp = doc.modelspace()
    msp.add_text("지상 2층 평면도", dxfattribs={"height": 400, "insert": (0, 0), "layer": "SH"})
    msp.add_text("A - 204", dxfattribs={"height": 300, "insert": (5000, 0), "layer": "SH"})
    msp.add_text("SD-01", dxfattribs={"height": 200, "insert": (100, 3000), "layer": "A-DOOR"})
    props = _parse(tmp_path, doc)["Model"]["properties"]
    assert props["drawingNumber"] == "A-204"
    assert props["drawingNumber_source"] == "title_block_text"
    assert props["drawing_category"] == "평면도" and props["storey"] == "2F"


def test_neutral_file_takes_number_next_to_label(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_text("구조 시방서 -1", dxfattribs={"height": 400, "insert": (0, 0)})
    msp.add_text("도면번호", dxfattribs={"height": 100, "insert": (8000, 200)})
    msp.add_text("S - 001", dxfattribs={"height": 150, "insert": (8000, 0)})
    msp.add_text("C1", dxfattribs={"height": 150, "insert": (100, 100)})
    props = _parse(tmp_path, doc)["Model"]["properties"]
    assert props["drawingNumber"] == "S-001"
    assert "label_proximity" in props["drawingNumber_method"]
    assert props["drawing_category"] == "시방서"


def test_inline_label_value_and_korean_number(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_text("DWG NO. 건축-01", dxfattribs={"height": 100, "insert": (0, 0)})
    props = _parse(tmp_path, doc)["Model"]["properties"]
    assert props["drawingNumber"] == "건축-01"


def test_no_sheet_evidence_gives_no_number(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_text("WD-12", dxfattribs={"height": 100, "insert": (0, 0), "layer": "A-WIND"})
    props = _parse(tmp_path, doc)["Model"]["properties"]
    assert "drawingNumber" not in props
