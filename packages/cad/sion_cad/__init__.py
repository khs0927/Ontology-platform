"""CAD (DXF) reading, analysis and ingestion for Sion. ``ezdxf`` is optional (extra ``cad``).

* :mod:`sion_cad.reader`   the shared DXF reading path (dependency-free import)
* :mod:`sion_cad.dxf`      ingestion into the Sion graph (needs the core install)
* :mod:`sion_cad.analysis` GOD-CAD evidence-linked geometry analysis (needs ``cad``)

Attributes are resolved lazily so ``sion_cad.reader`` can be used by packages
that do not install the Sion API (e.g. ``aec_intelligence``).
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "build_dxf_export": "sion_cad.dxf",
    "ingest_dxf": "sion_cad.dxf",
    "parse_dxf": "sion_cad.dxf",
    "parse_dxf_with_parser": "sion_cad.dxf",
    "dxf_census": "sion_cad.reader",
    "ezdxf_available": "sion_cad.reader",
    "open_dxf": "sion_cad.reader",
    "read_entities": "sion_cad.reader",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'sion_cad' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
