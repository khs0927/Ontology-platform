from pathlib import Path

from god_cad.adapters.dxf import ingest_dxf
from god_cad.models import Drawing
from god_cad.semantics import candidates
from god_cad.topology import endpoint_edges


def analyze(path: Path, drawing_id: str, units: str | None = None) -> Drawing:
    drawing = ingest_dxf(path, drawing_id, units)
    objects, semantic_edges = candidates(drawing)
    data = drawing.model_dump()
    data.update(semantic_objects=objects, edges=endpoint_edges(drawing) + semantic_edges)
    return Drawing.model_validate(data)
