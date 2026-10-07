from pathlib import Path

from fastapi.testclient import TestClient

from sion_api.main import create_app
from sion_drive_store.upload import publish_to_mounted_drive
from sion_graphrag.age import _label, _literal
from sion_ingestion.dxf_ingest import build_dxf_export, parse_dxf
from sion_ingestion.ifc_ingest import build_ifc_export, parse_ifc

IFC = """ISO-10303-21;
HEADER;
FILE_NAME('x.ifc');
ENDSEC;
DATA;
#1=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'Pump ''Room'' Project',$,$,$,$,$,$);
#2=IFCBUILDINGSTOREY('1aB',$,'Level 1',$,$,$,$,$,.ELEMENT.,0.);
#3=IFCWALL('2cD',$,'Wall A',$,$,$,$,$,$);
#4=IFCCARTESIANPOINT((0.,0.,0.));
#5=IFCWALL('2cD',$,'Wall A dup',$,$,$,$,$,$);
ENDSEC;
END-ISO-10303-21;
"""


def _client() -> TestClient:
    return TestClient(create_app(database_url="sqlite://", auto_create_schema=True))


def test_dxf_layer_zero_does_not_split_entities(tmp_path):
    path = tmp_path / "zero.dxf"
    path.write_text(
        "0\nSECTION\n2\nENTITIES\n0\nTEXT\n8\n0\n1\nNOTE\n"
        "0\nLWPOLYLINE\n8\n0\n70\n129\n0\nENDSEC\n0\nEOF\n",
        encoding="utf-8",
    )
    items = parse_dxf(path)
    assert [item["kind"] for item in items] == ["annotation", "space"]
    assert items[0]["layer"] == "0"
    export = build_dxf_export(path)
    assert export.expected_node_count == 3
    assert all(edge.verification_state == "unverified" for edge in export.edges)


def test_ifc_fallback_scanner_extracts_products(tmp_path):
    path = tmp_path / "model.ifc"
    path.write_text(IFC, encoding="utf-8")
    items, parser = parse_ifc(path, prefer_ifcopenshell=False)
    assert parser == "step-fallback"
    assert [item["ifc_class"] for item in items] == ["IFCPROJECT", "IFCBUILDINGSTOREY", "IFCWALL", "IFCWALL"]
    assert items[0]["name"] == "Pump 'Room' Project"
    export, _ = build_ifc_export(path, prefer_ifcopenshell=False)
    # duplicate GlobalId is collapsed; artifact + 3 unique items
    assert export.expected_node_count == 4
    assert export.expected_edge_count == 3


def test_ingest_routes_round_trip_and_validation(tmp_path):
    ifc = tmp_path / "model.ifc"
    ifc.write_text(IFC, encoding="utf-8")
    doc = tmp_path / "note.md"
    doc.write_text("# Pump room\n", encoding="utf-8")
    with _client() as c:
        assert c.post("/api/v1/ingest/ifc", json={}).status_code == 422
        assert c.post("/api/v1/ingest/ifc", json={"path": str(doc)}).status_code == 422
        result = c.post("/api/v1/ingest/ifc", json={"path": str(ifc)})
        assert result.status_code == 200, result.text
        assert result.json()["created_nodes"] >= 1
        again = c.post("/api/v1/ingest/ifc", json={"path": str(ifc)})
        assert again.status_code == 200
        assert again.json()["created_nodes"] == 0

        missing = c.post("/api/v1/ingest/documents", json={"paths": [str(tmp_path / "nope.md")]})
        assert missing.status_code == 422
        assert c.post("/api/v1/ingest/documents", json={"paths": "x"}).status_code == 422
        ok = c.post("/api/v1/ingest/documents", json={"paths": [str(doc)]})
        assert ok.status_code == 200, ok.text


def test_age_label_and_literal_sanitization():
    assert _label("Has-Part`) DETACH") == "Has_Part___DETACH"
    assert _label("1x") == "L_1x"
    assert _label("") == "Unlabeled"
    assert _literal("a'b$$c") == "a\\'b$ $c"


def test_publish_to_mounted_drive_is_non_destructive(tmp_path):
    stage = tmp_path / "stage"
    (stage / "objects").mkdir(parents=True)
    (stage / "objects" / "a.bin").write_bytes(b"abc")
    drive = tmp_path / "drive"
    first = publish_to_mounted_drive(stage, drive)
    assert first["published"] and first["copied"] == 1
    extra = Path(first["destination"]) / "keep.txt"
    extra.write_text("keep", encoding="utf-8")
    second = publish_to_mounted_drive(stage, drive)
    assert second["copied"] == 0
    assert extra.exists()
