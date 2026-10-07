import ezdxf
import pytest

from god_cad.models import Patch
from god_cad.pipeline import analyze


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "input.dxf"
    document = ezdxf.new("R2013", units=4)
    document.layers.new("WAL1")
    space = document.modelspace()
    space.add_line((0, 0), (1000, 0), dxfattribs={"layer": "WAL1"})
    space.add_line((1000, 0), (1000, 500), dxfattribs={"layer": "WAL1"})
    space.add_circle((5000, 5000), 100)
    space.add_text("Unparsed annotation")
    document.saveas(path)
    return path, analyze(path, "test-drawing")


@pytest.fixture
def patch_for():
    def factory(drawing, targets=None, **changes):
        values = dict(
            patch_id="test-patch",
            drawing_id=drawing.drawing_id,
            expected_revision=drawing.revision,
            operation="TRANSLATE_ENTITIES",
            target_ids=targets or [next(e.id for e in drawing.entities if e.cad_type == "CIRCLE")],
            vector_mm=(300, 0, 0),
            reason="Test simulation",
        )
        values.update(changes)
        return Patch(**values)

    return factory
