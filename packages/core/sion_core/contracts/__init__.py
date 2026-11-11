"""Machine-readable integration contracts for the bridged repositories.

The prose lives in ``docs/INTEGRATION_CONTRACTS.md``. The JSON Schemas
(draft 2020-12) under ``schemas/`` describe payloads that cross a repository
boundary, so .NET (power-cad-mcp, hs-steel-cad), TypeScript (korean-land-mcp)
and Python (All-In-Cad) peers can validate against the same files.

Validation needs ``jsonschema`` (part of the ``test``/``dev`` extras). Loading
schemas does not.

Every contract is pinned to an upstream commit (docs/INTEGRATION_CONTRACTS.md,
"Pinned upstream revisions") except those listed in :data:`DRAFT_CONTRACTS`:
their schema states what Sion expects, not what a pinned producer emits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
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
    "building-regulation-report/1": ("building-regulation-report-1.schema.json", "building-regulation-gateway produce-compliance-report", "Sion regulation evidence (advisory, evidence-only)"),
    "aec-cair-snapshot/1": ("aec-cair-snapshot-1.schema.json", "khs0927/Ontology aec ingest-dxf / ingest-file (CAIR)", "sion_cair.ingest -> Sion graph + evidence (unverified)"),
    "kordoc-evidence/1": ("kordoc-evidence-1.schema.json", "inspection-supervision-mcp (Kordoc parser)", "Sion evidence (evidence-only, project ACL)"),
}

#: contract name -> upstream repository, for contracts with **no pinned upstream commit**.
#: Draft contracts are Sion-side expectations; promote one by pinning a commit in the docs
#: table, adding upstream fixtures with provenance and removing it from this mapping.
DRAFT_CONTRACTS: dict[str, str] = {
    "kordoc-evidence/1": "khs0927/inspection-supervision-mcp",
}


def is_pinned(name: str) -> bool:
    """``False`` for draft contracts whose upstream revision is not pinned."""
    if name not in CONTRACTS:
        raise KeyError(f"unknown contract {name!r}; known: {', '.join(names())}")
    return name not in DRAFT_CONTRACTS


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


def _kordoc_evidence_checks(payload: Any) -> list[str]:
    """Checks JSON Schema cannot express for ``kordoc-evidence/1``."""
    found: list[str] = []
    source_text = payload.get("source_text") if isinstance(payload, dict) else None
    if isinstance(source_text, dict):
        quote, digest = source_text.get("quote"), source_text.get("quote_sha256")
        if isinstance(quote, str) and isinstance(digest, str):
            if hashlib.sha256(quote.encode("utf-8")).hexdigest() != digest:
                found.append("source_text/quote_sha256: does not match the SHA-256 of quote (UTF-8)")
    claims = payload.get("proposed_claims") if isinstance(payload, dict) else None
    if isinstance(claims, list):
        # only string ids are compared: a non-string claim_id is already a schema error, and
        # hashing an unhashable one (dict/list) must not crash validation of untrusted input
        ids = [c["claim_id"] for c in claims if isinstance(c, dict) and isinstance(c.get("claim_id"), str)]
        if len(ids) != len(set(ids)):
            found.append("proposed_claims: claim_id values must be unique")
    return found


#: contract name -> checks JSON Schema cannot express (run in addition to the schema)
_SEMANTIC_CHECKS: dict[str, Callable[[Any], list[str]]] = {
    "kordoc-evidence/1": _kordoc_evidence_checks,
}


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
    problems = [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]
    check = _SEMANTIC_CHECKS.get(name)
    if check is not None:
        problems += check(payload)
    return problems


def validate(name: str, payload: Any) -> None:
    """Raise ``ValueError`` listing every violation of the named contract."""
    problems = errors(name, payload)
    if problems:
        raise ValueError(f"{name} contract violated: " + "; ".join(problems))
