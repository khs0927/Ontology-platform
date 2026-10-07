"""Read-only subset adapter. Unsupported entities remain in the inventory."""

import hashlib
from pathlib import Path

from sion_cad.reader import open_dxf

from god_cad.identity import entity_id
from god_cad.models import Drawing, Entity, Geometry, SourceRef

FACTORS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
HEADER_UNITS = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}


def extract_geometry(entity, factor: float) -> tuple[Geometry, list[str]]:
    kind = entity.dxftype()
    reasons = []
    if kind not in {"LINE", "LWPOLYLINE", "CIRCLE", "ARC"}:
        return Geometry(kind="UNSUPPORTED"), [f"{kind}: geometry extraction is not implemented"]
    if tuple(entity.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1):
        reasons.append("Non-default OCS/extrusion requires a future adapter")
    if entity.dxf.get("thickness", 0) != 0:
        reasons.append("Non-zero entity thickness is outside the 2D subset")
    if kind == "LWPOLYLINE":
        if entity.has_arc:
            reasons.append("Polyline bulges must not be flattened into straight segments")
        if entity.has_width:
            reasons.append("Polyline width requires a future adapter")
    if reasons:
        return Geometry(kind="UNSUPPORTED"), reasons

    def point(value):
        return tuple(float(v) * factor for v in value)

    if kind == "LINE":
        points = [point(entity.dxf.start), point(entity.dxf.end)]
        geometry = Geometry(kind=kind, points=points)
    elif kind == "LWPOLYLINE":
        points = [point(p) for p in entity.vertices_in_wcs()]
        geometry = Geometry(kind=kind, points=points, closed=entity.closed)
    else:
        geometry = Geometry(
            kind=kind,
            points=[point(entity.dxf.center)],
            radius=float(entity.dxf.radius) * factor,
            start_angle=float(entity.dxf.start_angle) if kind == "ARC" else None,
            end_angle=float(entity.dxf.end_angle) if kind == "ARC" else None,
        )
    if any(p[2] != 0 for p in geometry.points):
        return Geometry(kind="UNSUPPORTED"), ["Non-zero Z is outside the 2D subset"]
    return geometry, []


def ingest_dxf(path: Path, drawing_id: str, units: str | None = None) -> Drawing:
    if path.suffix.lower() != ".dxf":
        raise ValueError("This adapter accepts DXF only; native DWG is not implemented")
    revision = hashlib.sha256(path.read_bytes()).hexdigest()
    # Shared monorepo reader: strict read, ezdxf.recover fallback, CP949 detection.
    document, read_warnings = open_dxf(path)
    source_units = units or HEADER_UNITS.get(int(document.header.get("$INSUNITS", 0)))
    if source_units not in FACTORS:
        raise ValueError("Unknown/unsupported source units; provide --units mm|cm|m|in|ft")
    factor = FACTORS[source_units]
    warnings = [
        "Only top-level Model entities are inventoried; "
        "paper space and block contents are excluded",
        "DXF handles are not proven to equal original DWG handles",
        "No native audit, full dependency extraction, or independent visual verification has run",
    ]
    entities = []
    for native in document.modelspace():
        geometry, limitations = extract_geometry(native, factor)
        handle = native.dxf.handle.upper()
        layer_name = native.dxf.layer
        layer = document.layers.get(layer_name) if layer_name in document.layers else None
        if layer is None:
            limitations.append("Missing layer table entry")
        entities.append(
            Entity(
                id=entity_id(drawing_id, handle),
                source=SourceRef(
                    drawing_id=drawing_id, revision=revision, format="DXF", handle=handle
                ),
                cad_type=native.dxftype(),
                layer=layer_name,
                layer_locked=layer.is_locked() if layer else True,
                geometry=geometry,
                analysis_supported=not limitations,
                limitations=limitations,
            )
        )
    warnings.extend(read_warnings)
    unsupported = sum(not e.analysis_supported for e in entities)
    if hashlib.sha256(path.read_bytes()).hexdigest() != revision:
        raise ValueError("Source changed while parsing; retry on a stable copy")
    if unsupported:
        warnings.append(f"{unsupported} top-level entities are unsupported; see entity limitations")
    return Drawing(
        drawing_id=drawing_id,
        revision=revision,
        source_name=path.name,
        source_units=source_units,
        unit_evidence="user_override" if units else "header",
        entities=sorted(entities, key=lambda e: e.id),
        warnings=warnings,
    )
