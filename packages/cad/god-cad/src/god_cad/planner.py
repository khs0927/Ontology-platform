"""Pure translation simulation. This is not a native edit or a full CAD validator."""

from god_cad.models import Change, Drawing, Geometry, Patch, PlanReport
from god_cad.topology import endpoint_edges


def translate(geometry: Geometry, vector) -> Geometry:
    data = geometry.model_dump()
    data["points"] = [tuple(a + b for a, b in zip(p, vector, strict=True)) for p in geometry.points]
    return Geometry.model_validate(data)


def dry_run(drawing: Drawing, patch: Patch) -> PlanReport:
    errors = []
    warnings = [
        "Simulation only: native_write_eligible is always false",
        "No collision, room, dimension, hatch, native DWG or visual validation is implemented",
        "Edit dependencies are incomplete; never interpret an empty edge list as no dependencies",
    ]
    targets = set(patch.target_ids)
    entities = {e.id: e for e in drawing.entities}
    if patch.drawing_id != drawing.drawing_id:
        errors.append("Drawing identity mismatch")
    if patch.expected_revision != drawing.revision:
        errors.append("Stale revision: re-analyze and re-plan")
    if patch.vector_mm[2] != 0:
        errors.append("Only XY translations are supported")
    for target in sorted(targets):
        entity = entities.get(target)
        if entity is None:
            errors.append(f"Unknown entity: {target}")
        elif not entity.analysis_supported or entity.geometry.kind == "UNSUPPORTED":
            errors.append(f"Unsupported geometry: {target}")
        elif entity.layer_locked:
            errors.append(f"Locked layer: {target}")

    # Recompute geometric edges rather than trusting that a supplied graph is complete.
    dependencies = endpoint_edges(drawing) + [e for e in drawing.edges if e.graph == "edit"]
    affected = set(targets)
    changed = True
    while changed:
        changed = False
        for edge in dependencies:
            neighbors = set()
            if edge.source in affected:
                neighbors.add(edge.target)
            if edge.graph == "topology" and edge.target in affected:
                neighbors.add(edge.source)
            if neighbors - affected:
                affected.update(neighbors)
                changed = True
    missing = affected - targets
    if missing:
        errors.append("Affected entities omitted from patch: " + ", ".join(sorted(missing)))

    changes = []
    if not errors:
        for target in sorted(targets):
            before = entities[target].geometry
            changes.append(
                Change(entity_id=target, before=before, after=translate(before, patch.vector_mm))
            )
    return PlanReport(
        patch_id=patch.patch_id,
        status="rejected" if errors else "simulation_passed",
        affected_ids=sorted(affected),
        errors=errors,
        warnings=warnings,
        changes=changes,
    )
