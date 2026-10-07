import hashlib

import ezdxf
import pytest

from god_cad.pipeline import analyze


def test_identity_evidence_and_unsupported_inventory(sample):
    path, drawing = sample
    assert len(drawing.entities) == 4
    assert drawing.revision == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len({e.id for e in drawing.entities}) == 4
    assert all(s.status == "candidate" for s in drawing.semantic_objects)
    assert all(not s.evidence[0].calibrated for s in drawing.semantic_objects)
    text = next(e for e in drawing.entities if e.cad_type == "TEXT")
    assert not text.analysis_supported
    assert text.limitations
    assert len([e for e in drawing.edges if e.graph == "topology"]) == 1
    assert analyze(path, "test-drawing") == drawing
    other = analyze(path, "other-drawing")
    assert {e.id for e in drawing.entities}.isdisjoint(e.id for e in other.entities)


@pytest.mark.parametrize("units,factor", [(1, 25.4), (2, 304.8), (4, 1), (5, 10), (6, 1000)])
def test_units_are_normalized(tmp_path, units, factor):
    path = tmp_path / "units.dxf"
    doc = ezdxf.new(units=units)
    doc.modelspace().add_line((1, 2), (3, 4))
    doc.saveas(path)
    result = analyze(path, "units")
    assert result.entities[0].geometry.points[0] == pytest.approx((factor, factor * 2, 0))


def test_unknown_units_need_explicit_input(tmp_path):
    path = tmp_path / "unitless.dxf"
    doc = ezdxf.new(units=0)
    doc.saveas(path)
    with pytest.raises(ValueError, match="Unknown/unsupported source units"):
        analyze(path, "unitless")
    assert analyze(path, "unitless", "mm").unit_evidence == "user_override"


def test_complex_entities_are_never_flattened_silently(tmp_path):
    path = tmp_path / "complex.dxf"
    doc = ezdxf.new(units=4)
    space = doc.modelspace()
    space.add_lwpolyline([(0, 0, 1), (100, 0, 0)], format="xyb")
    space.add_lwpolyline([(0, 0), (100, 0)], dxfattribs={"const_width": 10})
    space.add_circle((0, 0), 10, dxfattribs={"extrusion": (0, 0, -1)})
    space.add_line((0, 0, 1), (10, 0, 1))
    doc.blocks.new("BLOCK_A").add_line((0, 0), (1, 1))
    space.add_blockref("BLOCK_A", (0, 0))
    doc.saveas(path)
    result = analyze(path, "complex")
    assert len(result.entities) == 5
    assert all(not e.analysis_supported and e.limitations for e in result.entities)


def test_revision_changes_but_source_ids_persist(sample):
    path, before = sample
    doc = ezdxf.readfile(path)
    doc.modelspace().query("CIRCLE").first.dxf.center = (6000, 6000)
    doc.saveas(path)
    after = analyze(path, before.drawing_id)
    assert before.revision != after.revision
    assert [e.id for e in before.entities] == [e.id for e in after.entities]


def test_supported_polyline_and_arc_preserve_geometry(tmp_path):
    path = tmp_path / "curves.dxf"
    doc = ezdxf.new(units=4)
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 200)], close=True)
    doc.modelspace().add_arc((500, 600), 50, 20, 280)
    doc.saveas(path)
    drawing = analyze(path, "curves")
    arc = next(e.geometry for e in drawing.entities if e.cad_type == "ARC")
    poly = next(e.geometry for e in drawing.entities if e.cad_type == "LWPOLYLINE")
    assert arc.points == [(500, 600, 0)]
    assert (arc.radius, arc.start_angle, arc.end_angle) == (50, 20, 280)
    assert poly.closed
    assert poly.points == [(0, 0, 0), (100, 0, 0), (100, 200, 0)]
