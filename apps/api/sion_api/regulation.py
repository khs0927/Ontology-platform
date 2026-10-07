"""Bridge from the Sion API to the ArchOntos rule evaluator (packages/regulation).

ArchOntos' JSON rule DSL is fail-closed: a missing fact or an unknown operator
yields REVIEW, never PASS/FAIL. Sion only *evaluates* here; it does not compile,
approve or persist rules (that stays in the ArchOntos services and their
four-eyes review workflow). Facts may come from a Sion entity's ``properties``.
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
