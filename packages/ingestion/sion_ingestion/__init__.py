"""Sion ingestion adapters.

Attributes are resolved lazily so ``import sion_ingestion`` stays cheap and
never pulls optional extras.
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "AecCairAdapter": "sion_cair.adapter",
    "AecCairConfig": "sion_cair.adapter",
    "AecCairError": "sion_cair.adapter",
    "GraphImportError": "sion_ingestion.map_import",
    "MapExport": "sion_ingestion.map_import",
    "import_map_export": "sion_ingestion.map_import",
    "load_map_export": "sion_ingestion.map_import",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'sion_ingestion' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
