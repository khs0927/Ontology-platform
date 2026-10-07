import hashlib

import pytest
from pydantic import ValidationError

from god_cad.adapters.native import UnavailableNativeExecutor
from god_cad.models import Drawing, Edge
from god_cad.planner import dry_run


def test_simulation_is_pure_and_never_authorizes_native_write(sample, patch_for):
    path, drawing = sample
    before = drawing.model_dump_json()
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    patch = patch_for(drawing)
    report = dry_run(drawing, patch)
    assert report.status == "simulation_passed"
    assert report.changes[0].after.points[0] == (5300, 5000, 0)
    assert report.changes[0].after.radius == 100
    assert not report.native_write_eligible
    assert drawing.model_dump_json() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    with pytest.raises(NotImplementedError):
        UnavailableNativeExecutor().execute(patch)


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"expected_revision": "0" * 64}, "Stale revision"),
        ({"drawing_id": "wrong"}, "Drawing identity"),
        ({"target_ids": ["missing"]}, "Unknown entity"),
        ({"vector_mm": (0, 0, 1)}, "Only XY"),
    ],
)
def test_invalid_plan_is_rejected(sample, patch_for, changes, message):
    _, drawing = sample
    report = dry_run(drawing, patch_for(drawing, **changes))
    assert report.status == "rejected"
    assert report.changes == []
    assert any(message in error for error in report.errors)


def test_connected_lines_must_be_explicit_targets_even_if_edges_removed(sample, patch_for):
    _, drawing = sample
    drawing.edges = []
    lines = [e.id for e in drawing.entities if e.cad_type == "LINE"]
    rejected = dry_run(drawing, patch_for(drawing, [lines[0]]))
    assert rejected.status == "rejected"
    assert set(rejected.affected_ids) == set(lines)
    accepted = dry_run(drawing, patch_for(drawing, lines))
    assert accepted.status == "simulation_passed"
    assert len(accepted.changes) == 2


def test_directed_dependency_closure_with_cycle_terminates(sample, patch_for):
    _, drawing = sample
    ids = [e.id for e in drawing.entities]
    for left, right in [(ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])]:
        drawing.edges.append(
            Edge(
                source=left,
                target=right,
                graph="edit",
                relation="requires_update",
                evidence="fixture",
            )
        )
    report = dry_run(drawing, patch_for(drawing, [ids[0]]))
    assert set(ids[:3]) <= set(report.affected_ids)
    assert report.status == "rejected"


def test_unsupported_and_locked_entities_rejected(sample, patch_for):
    _, drawing = sample
    text = next(e for e in drawing.entities if e.cad_type == "TEXT")
    assert dry_run(drawing, patch_for(drawing, [text.id])).status == "rejected"
    circle = next(e for e in drawing.entities if e.cad_type == "CIRCLE")
    circle.layer_locked = True
    assert dry_run(drawing, patch_for(drawing, [circle.id])).status == "rejected"


@pytest.mark.parametrize("vector", [(float("nan"), 0, 0), (float("inf"), 0, 0), (0, 0, 0)])
def test_nonfinite_and_empty_translations_rejected(sample, patch_for, vector):
    with pytest.raises(ValidationError):
        patch_for(sample[1], vector_mm=vector)


def test_contract_rejects_dangling_reference_and_duplicate_identity(sample):
    _, drawing = sample
    data = drawing.model_dump()
    data["entities"].append(data["entities"][0])
    with pytest.raises(ValidationError, match="Duplicate"):
        Drawing.model_validate(data)
    data = drawing.model_dump()
    data["edges"][0]["target"] = "missing"
    with pytest.raises(ValidationError):
        Drawing.model_validate(data)
