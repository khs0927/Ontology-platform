import json
from xml.etree import ElementTree

from god_cad.cli import main
from god_cad.render import render_svg


def test_end_to_end_cli_and_schema(sample, patch_for, tmp_path):
    path, drawing = sample
    output = tmp_path / "drawing.json"
    assert main(["ingest", str(path), "--drawing-id", "test-drawing", "--out", str(output)]) == 0
    assert json.loads(output.read_text())["revision"] == drawing.revision
    patch_path = tmp_path / "patch.json"
    patch_path.write_text(patch_for(drawing).model_dump_json(), encoding="utf-8")
    report = tmp_path / "report.json"
    assert main(["plan", str(output), str(patch_path), "--out", str(report)]) == 0
    assert json.loads(report.read_text())["native_write_eligible"] is False
    schema = tmp_path / "schema.json"
    assert main(["schema", "patch", "--out", str(schema)]) == 0
    assert json.loads(schema.read_text())["additionalProperties"] is False


def test_cli_refuses_overwrite_and_returns_nonzero_for_invalid_input(sample, tmp_path):
    path, _ = sample
    original = path.read_bytes()
    assert main(["ingest", str(path), "--drawing-id", "test", "--out", str(path)]) == 2
    assert path.read_bytes() == original
    broken = tmp_path / "invalid.json"
    broken.write_text("{}")
    assert main(["plan", str(broken), str(broken), "--out", str(tmp_path / "r.json")]) == 2


def test_svg_preview_has_rendered_geometry(sample):
    xml = ElementTree.fromstring(render_svg(sample[0]))
    assert xml.tag.endswith("svg")
    assert len(list(xml.iter("{http://www.w3.org/2000/svg}path"))) > 0
