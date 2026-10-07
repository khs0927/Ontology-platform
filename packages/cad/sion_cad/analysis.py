"""Evidence-linked DXF analysis from GOD-CAD (packages/cad/god-cad), exposed to Sion.

GOD-CAD inventories top-level model-space entities with stable identities
(logical drawing id + handle, SHA-256 revision), extracts a limited 2D geometry
subset in millimetres, proposes *unconfirmed* semantic candidates from layer
priors (WAL*/COL/DOOR/WIN) and computes endpoint topology. Every unsupported
case is reported as a limitation instead of being guessed. Reading goes through
:func:`sion_cad.reader.open_dxf`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sion_core import MissingExtra, require


class AnalysisUnavailable(RuntimeError):
    pass


def default_drawing_id(path: Path) -> str:
    return "dxf:" + hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]


def analyze_dxf(path: str | Path, *, drawing_id: str | None = None, units: str | None = None) -> dict[str, Any]:
    """Run the GOD-CAD pipeline and return its ``Drawing`` contract as JSON-ready data."""
    try:
        require("ezdxf", extra="cad")
        pipeline = require("god_cad.pipeline", extra="cad")
    except MissingExtra as exc:
        raise AnalysisUnavailable(str(exc)) from exc
    source = Path(path)
    drawing = pipeline.analyze(source, drawing_id or default_drawing_id(source), units)
    data = drawing.model_dump(mode="json")
    data["analysis_engine"] = "god-cad"
    return data
