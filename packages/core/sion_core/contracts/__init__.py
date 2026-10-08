"""Machine-readable integration contracts for the bridged repositories.

The prose lives in ``docs/INTEGRATION_CONTRACTS.md``. The JSON Schemas
(draft 2020-12) under ``schemas/`` describe payloads that cross a repository
boundary, so .NET (power-cad-mcp, hs-steel-cad), TypeScript (korean-land-mcp)
and Python (HS-CAD, All-In-Cad) peers can validate against the same files.

Validation needs ``jsonschema`` (part of the ``test``/``dev`` extras). Loading
schemas does not.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from sion_core.optional import MissingExtra

SCHEMA_PACKAGE = "sion_core.contracts.schemas"

#: contract name -> (schema file, producer repository, consumer)
CONTRACTS: dict[str, tuple[str, str, str]] = {
    "sion-aec-query-response": ("sion-aec-query-response.schema.json", "Sion API", "power-cad-mcp cad_context_query"),
    "power-cad-execution-receipt/1": ("power-cad-execution-receipt-1.schema.json", "power-cad-mcp", "Sion evidence (evidence-only)"),
    "hs-steel-draw-plan/1": ("hs-steel-draw-plan-1.schema.json", "hs-steel-cad", "power-cad-mcp (Sion: provenance only)"),
    "hs-steel-section-catalog/1": ("hs-steel-section-catalog-1.schema.json", "hs-steel-cad SectionCatalogHandoff", "power-cad-mcp cad_hs_steel_catalog_prepare; Sion aec section evidence (read-only)"),
    "hs-steel-asset-registry/1": ("hs-steel-asset-registry-1.schema.json", "hs-steel-cad tools/AssetRegistry", "power-cad-mcp cad_hs_* (Sion: provenance only, upstream schema verbatim)"),
    "korean-land-parcel-analysis/2": ("korean-land-parcel-analysis-2.schema.json", "korean-land-mcp analyze_parcel", "Sion regulation facts"),
    "all-in-cad-dxf-evidence": ("all-in-cad-dxf-evidence.schema.json", "Sion sion_cad.reader.dxf_census / All-In-Cad inspect_dxf", "cross-lane DXF verification"),
    "hs-cad-scan-objects": ("hs-cad-scan-objects.schema.json", "HS-CAD export_objects_json", "Sion evidence"),
    "hs-cad-command": ("hs-cad-command.schema.json", "AI planners", "HS-CAD run-command (Sion never emits these)"),
}


def names() -> list[str]:
    return sorted(CONTRACTS)


@lru_cache(maxsize=None)
def _load(filename: str) -> str:
    return resources.files(SCHEMA_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def load(name: str) -> dict[str, Any]:
    """Return the JSON Schema for a contract name (see :data:`CONTRACTS`)."""
    try:
        filename = CONTRACTS[name][0]
    except KeyError as exc:
        raise KeyError(f"unknown contract {name!r}; known: {', '.join(names())}") from exc
    return json.loads(_load(filename))


def errors(name: str, payload: Any) -> list[str]:
    """Validate ``payload``; return human-readable errors (empty list = valid)."""
    try:
        import jsonschema
    except ImportError as exc:
        raise MissingExtra("jsonschema", "test") from exc
    schema = load(name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema, format_checker=validator_cls.FORMAT_CHECKER)
    found = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]


def validate(name: str, payload: Any) -> None:
    """Raise ``ValueError`` listing every violation of the named contract."""
    problems = errors(name, payload)
    if problems:
        raise ValueError(f"{name} contract violated: " + "; ".join(problems))
