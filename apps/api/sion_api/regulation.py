"""Bridge from the Sion API to the ArchOntos rule evaluator (packages/regulation).

ArchOntos' JSON rule DSL is fail-closed: a missing fact or an unknown operator
yields REVIEW, never PASS/FAIL. Sion only *evaluates* here; it does not compile,
approve or persist rules (that stays in the ArchOntos services and their
four-eyes review workflow). Facts may come from a Sion entity's ``properties``
and from a korean-land-mcp ``analyze_parcel`` record (``land.*`` facts, see
:func:`facts_from_land_parcel` and docs/INTEGRATION_CONTRACTS.md).
"""

from __future__ import annotations

from typing import Any

from sion_core import MissingExtra, extras_report, require


class RegulationUnavailable(RuntimeError):
    pass


def status() -> dict[str, Any]:
    info = extras_report()["regulation"]
    return {
        "engine": "archontos.rules.engine",
        "available": bool(info["installed"]),
        "missing": info["missing"],
        "install": "pip install 'sion-ontology-platform[regulation]'",
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def evaluate(rule_document: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    try:
        engine = require("archontos.rules.engine", extra="regulation")
    except MissingExtra as exc:
        raise RegulationUnavailable(str(exc)) from exc
    except ImportError as exc:  # e.g. greenlet missing for sqlalchemy.ext.asyncio
        raise RegulationUnavailable(
            f"{exc}. Install: pip install 'sion-ontology-platform[regulation]'"
        ) from exc
    try:
        result = engine.evaluate_rule(rule_document, facts)
    except engine.RuleEvaluationError as exc:
        # Malformed rule documents are reported, never coerced into an outcome.
        return {"applicable": True, "outcome": "REVIEW", "reason": "Rule could not be evaluated", "details": {"error": str(exc)}}
    data = result.model_dump(mode="json")
    return data


def merge_facts(entity_properties: dict[str, Any] | None, facts: dict[str, Any] | None) -> dict[str, Any]:
    return _deep_merge(entity_properties or {}, facts or {})


# --------------------------------------------------------------------------- korean-land-mcp

LAND_CONTRACT = "korean-land-parcel-analysis/2"

# V-World layer ids per analyze_parcel family (korean-land-mcp src/tools/analyze_parcel.ts).
_LAND_FAMILIES: dict[str, frozenset[str]] = {
    "use_zone": frozenset({"LT_C_UQ111", "LT_C_UQ112", "LT_C_UQ113", "LT_C_UQ114"}),
    "use_district": frozenset(
        {"LT_C_UQ121", "LT_C_UQ123", "LT_C_UQ124", "LT_C_UQ125", "LT_C_UQ126", "LT_C_UQ128", "LT_C_UQ129", "LT_C_UQ130"}
    ),
    "use_area": frozenset({"LT_C_UD801", "LT_C_UQ162"}),
    "land_transaction_permit": frozenset({"LT_C_UQ141"}),
    "district_plan": frozenset({"LT_C_UPISUQ161", "LT_C_UPISUQ171"}),
    "urban_facility": frozenset(f"LT_C_UPISUQ15{i}" for i in range(1, 10)),
}
_GREENBELT_LAYER = "LT_C_UD801"  # 개발제한구역


def _land_family(layer: str) -> str:
    for family, layers in _LAND_FAMILIES.items():
        if layer in layers:
            return family
    return "other_law"


def facts_from_land_parcel(record: dict[str, Any]) -> dict[str, Any]:
    """Turn a korean-land-mcp ``analyze_parcel`` record into fail-closed ``land.*`` rule facts.

    Contract: ``korean-land-parcel-analysis/2`` (docs/INTEGRATION_CONTRACTS.md). Positive overlay
    hits are always kept. A *negative* overlay fact (``False`` / empty list) is omitted, so a rule
    that needs it evaluates to REVIEW, when the layer family returned a query error or when the
    overlays were matched by point instead of the parcel polygon. Omitted names are listed in
    ``land.unverified``. Values are copied, never inferred.
    """
    if not isinstance(record, dict):
        raise ValueError("land parcel record must be a JSON object")
    missing = [key for key in ("parcel", "zoning", "source") if not isinstance(record.get(key), dict)]
    if missing:
        raise ValueError(f"land parcel record lacks object member(s): {', '.join(missing)}")

    parcel = record["parcel"]
    zoning = record["zoning"]
    precision = record["source"].get("precision")
    errors = [e for e in record.get("layer_errors") or [] if isinstance(e, dict)]
    errored = {_land_family(str(e.get("layer", ""))) for e in errors}
    if any(not str(e.get("layer", "")).startswith("LT_C_") for e in errors):
        errored |= {*_LAND_FAMILIES, "other_law"}  # unknown layer: trust no negative overlay
    negatives_trusted = precision == "polygon"

    land: dict[str, Any] = {"contract": LAND_CONTRACT, "precision": precision, "layer_error_count": len(errors)}
    unverified: list[str] = []

    for key in ("pnu", "jibun", "jimok", "jimok_code", "is_mountain_register", "address"):
        if parcel.get(key) is not None:
            land[key] = parcel[key]
    admin = parcel.get("administrative") or {}
    for key in ("sido", "sigg", "emd_dong"):
        if admin.get(key):
            land[key] = admin[key]

    def hits(value: Any) -> list[dict[str, Any]]:
        return [h for h in value if isinstance(h, dict)] if isinstance(value, list) else []

    def overlay(name: str, family: str, found: bool, values: list[Any] | None = None, list_name: str | None = None):
        reliable_negative = negatives_trusted and family not in errored
        if found or reliable_negative:
            land[name] = found
        else:
            unverified.append(name)
        if list_name is not None:
            if family not in errored and (values or reliable_negative):
                land[list_name] = values or []
            elif values:
                land[list_name] = values  # partial but true hits
                unverified.append(list_name)
            else:
                unverified.append(list_name)

    zones = [h["name"] for h in hits(zoning.get("use_zone")) if h.get("name") and h["name"] != "(unnamed)"]
    if zones:
        land["use_zone"] = zones[0]
    else:
        unverified.append("use_zone")  # no named 용도지역 returned: never guess one
    overlay("has_use_zone_hit", "use_zone", bool(hits(zoning.get("use_zone"))), zones, "use_zones")

    districts = [h.get("name") for h in hits(zoning.get("use_district")) if h.get("name")]
    overlay("has_use_district", "use_district", bool(districts), districts, "use_districts")

    areas = hits(zoning.get("use_area"))
    overlay("has_use_area", "use_area", bool(areas), [h.get("name") for h in areas if h.get("name")], "use_areas")
    overlay("in_development_restriction_zone", "use_area", any(h.get("layer") == _GREENBELT_LAYER for h in areas))

    overlay("land_transaction_permit", "land_transaction_permit", bool(hits(zoning.get("land_transaction_permit"))))

    plans = [h.get("name") for h in hits(record.get("district_plan")) if h.get("name")]
    overlay("in_district_plan", "district_plan", bool(plans), plans, "district_plan_names")

    facilities = hits(record.get("urban_facility"))
    overlay("urban_facility_overlap", "urban_facility", bool(facilities))

    designations = hits(record.get("other_law_designations"))
    names = [d.get("name") for d in designations if d.get("name")]
    overlay("has_other_law_designation", "other_law", bool(names), names, "other_law_names")
    priority = any(d.get("triggers_priority_delegation") is True for d in designations)
    hint = record.get("priority_delegation_hint") or {}
    priority = priority or hint.get("applies") is True
    overlay("priority_delegation", "other_law", priority)

    buildings = record.get("buildings")
    if isinstance(buildings, dict) and isinstance(buildings.get("present"), bool):
        land["buildings_present"] = buildings["present"]
        if isinstance(buildings.get("count"), int):
            land["building_count"] = buildings["count"]

    land["unverified"] = sorted(set(unverified))
    return {"land": land}


def land_facts_checked(record: Any) -> dict[str, Any]:
    """:func:`facts_from_land_parcel` after JSON Schema validation (when ``jsonschema`` is installed)."""
    from sion_core import contracts

    try:
        problems = contracts.errors(LAND_CONTRACT, record)
    except MissingExtra:
        problems = []  # structural checks in facts_from_land_parcel still apply
    if problems:
        raise ValueError(f"{LAND_CONTRACT} contract violated: " + "; ".join(problems[:10]))
    return facts_from_land_parcel(record)
