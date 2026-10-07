"""Optional OSS parser paths. Skipped unless the extras are installed."""

import pytest
from sion_ingestion.dxf_ingest import parse_dxf, parse_dxf_with_parser
from sion_ingestion.ifc_ingest import build_ifc_export, parse_ifc


def test_ezdxf_parser_matches_fallback(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("A-NOTE")
    msp.add_text("DOOR", dxfattribs={"layer": "A-NOTE"})
    msp.add_mtext("PUMP ROOM", dxfattribs={"layer": "0"})
    msp.add_line((0, 0), (1, 0))
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1)], close=True)
    doc.blocks.new("DOOR_BLOCK")
    msp.add_blockref("DOOR_BLOCK", (0, 0))
    path = tmp_path / "plan.dxf"
    doc.saveas(path)

    items, parser = parse_dxf_with_parser(path)
    assert parser == "ezdxf"
    kinds = sorted(item["kind"] for item in items)
    assert kinds == ["annotation", "annotation", "block", "segment", "space"]
    assert {i["name"] for i in items if i["kind"] == "annotation"} == {"DOOR", "PUMP ROOM"}
    fallback = parse_dxf(path, prefer_ezdxf=False)
    assert sorted(i["kind"] for i in fallback) == kinds


def test_ifcopenshell_parser(tmp_path):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    import ifcopenshell.guid

    model = ifcopenshell.file(schema="IFC4")
    for cls, name in (("IfcProject", "Demo"), ("IfcSite", "Site"), ("IfcWall", "Wall A")):
        model.create_entity(cls, GlobalId=ifcopenshell.guid.new(), Name=name)
    path = tmp_path / "demo.ifc"
    model.write(str(path))

    items, parser = parse_ifc(path)
    assert parser == "ifcopenshell"
    assert {"Demo", "Site", "Wall A"} <= {i["name"] for i in items}
    fallback, fb_parser = parse_ifc(path, prefer_ifcopenshell=False)
    assert fb_parser == "step-fallback"
    assert {"Demo", "Site", "Wall A"} <= {i["name"] for i in fallback}
    export, _ = build_ifc_export(path)
    assert export.expected_edge_count == len(export.edges)


def test_google_drive_client_importable():
    pytest.importorskip("googleapiclient")
    from googleapiclient.http import MediaFileUpload  # noqa: F401
