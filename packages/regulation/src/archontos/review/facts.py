"""Bitemporal fact store (W05; scenarios S02, S03, S12, S13, S17, S21, S22).

``validity`` is when a fact holds in the world, ``recorded_at``/``superseded_at`` is when this
system believed it. Nothing is deleted: a correction closes the old row and adds a new one. A
missing, partial or conflicting value stays unknown; it is never turned into ``False``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from archontos.review.model import (
    Evidence,
    Fact,
    FactStatus,
    Interval,
    SourceRef,
    canonical_digest,
)

LAND_CONTRACT = "korean-land-parcel-analysis/2"

# Facts that are never inferred from register entries such as 지목 (section 6).
LEGAL_STATUS_PATHS = ("legal.is_farmland", "legal.is_mountain_land")


@dataclass(frozen=True, slots=True)
class FactResolution:
    """What the store can say about one path at one point on both time axes."""

    status: FactStatus
    value: Any = None
    facts: tuple[Fact, ...] = ()
    reason: str | None = None

    @property
    def known(self) -> bool:
        return self.status not in {FactStatus.UNKNOWN, FactStatus.DISPUTED}

    @property
    def fact_ids(self) -> list[str]:
        return [fact.fact_id for fact in self.facts]

    @property
    def evidence_ids(self) -> list[str]:
        return sorted({eid for fact in self.facts for eid in fact.evidence_ids})


class FactStore:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}

    def add(self, fact: Fact) -> Fact:
        existing = self._facts.get(fact.fact_id)
        if existing is not None and existing != fact:
            raise ValueError(f"fact {fact.fact_id} already exists with other content")
        self._facts[fact.fact_id] = fact.model_copy(deep=True)
        return self._facts[fact.fact_id]

    def supersede(self, fact_id: str, replacement: Fact) -> Fact:
        """Close ``fact_id`` at the replacement's ``recorded_at`` and add the replacement."""

        old = self._facts[fact_id]
        if old.superseded_at is not None:
            raise ValueError(f"fact {fact_id} is already superseded")
        if replacement.recorded_at < old.recorded_at:
            raise ValueError("a replacement cannot be recorded before the fact it supersedes")
        self._facts[fact_id] = old.model_copy(update={"superseded_at": replacement.recorded_at})
        return self.add(replacement)

    def history(self, path: str, subject: str) -> list[Fact]:
        rows = [f for f in self._facts.values() if f.path == path and f.subject == subject]
        return sorted(rows, key=lambda f: (f.recorded_at, f.fact_id))

    def all(self) -> list[Fact]:
        return sorted(self._facts.values(), key=lambda f: (f.subject, f.path, f.fact_id))

    def paths(self, subject: str) -> list[str]:
        return sorted({f.path for f in self._facts.values() if f.subject == subject})

    def current(
        self,
        path: str,
        subject: str,
        as_of_valid: date,
        as_of_recorded: datetime | None = None,
    ) -> FactResolution:
        """Resolve one path. Conflicting rows are all preserved under ``DISPUTED``."""

        if as_of_recorded is None:
            believed = [f for f in self.history(path, subject) if f.superseded_at is None]
        else:
            believed = [
                f
                for f in self.history(path, subject)
                if f.recorded_at <= as_of_recorded
                and (f.superseded_at is None or f.superseded_at > as_of_recorded)
            ]
        if not believed:
            return FactResolution(FactStatus.UNKNOWN, reason="no fact recorded")

        decisions = [(fact, fact.validity.contains(as_of_valid)) for fact in believed]
        in_force = [fact for fact, decided in decisions if decided is True]
        undated = [fact for fact, decided in decisions if decided is None]
        if not in_force:
            if undated:
                return FactResolution(
                    FactStatus.UNKNOWN,
                    facts=tuple(undated),
                    reason=f"validity start unknown, cannot place the fact on {as_of_valid}",
                )
            return FactResolution(FactStatus.UNKNOWN, reason=f"no fact valid on {as_of_valid}")

        valued = [fact for fact in in_force if fact.status is not FactStatus.UNKNOWN]
        if not valued:
            return FactResolution(
                FactStatus.UNKNOWN, facts=tuple(in_force), reason=in_force[0].note
            )
        digests = {canonical_digest([fact.value, fact.unit]) for fact in valued}
        if len(digests) > 1 or any(fact.status is FactStatus.DISPUTED for fact in valued):
            return FactResolution(
                FactStatus.DISPUTED, facts=tuple(valued), reason="conflicting sources preserved"
            )
        sources = {tuple(sorted(fact.evidence_ids)) for fact in valued if fact.evidence_ids}
        if len(valued) > 1 and len(sources) > 1:
            return FactResolution(FactStatus.CORROBORATED, valued[0].value, tuple(valued))
        return FactResolution(valued[0].status, valued[0].value, tuple(valued))


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        nested = target.setdefault(part, {})
        if not isinstance(nested, dict):
            raise ValueError(f"fact path {path} collides with a scalar fact")
        target = nested
    target[parts[-1]] = value


def to_rule_facts(
    store: FactStore,
    subject: str | Iterable[str],
    day: date,
    *,
    required: Iterable[str] = (),
    as_of_recorded: datetime | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build rule-engine input as ``(facts, used_fact_ids, missing_paths)``.

    Unknown, disputed and partly observed values are omitted, so the fail-closed rule engine
    answers REVIEW instead of comparing against a guess (S13, S22).
    """

    subjects = [subject] if isinstance(subject, str) else list(subject)
    facts: dict[str, Any] = {}
    units: dict[str, str] = {}
    used: list[str] = []
    missing: set[str] = set(required)
    for name in subjects:
        for path in store.paths(name):
            resolution = store.current(path, name, day, as_of_recorded)
            partial = any(fact.observation_scope != "whole" for fact in resolution.facts)
            if not resolution.known or partial:
                missing.add(path)
                continue
            _set_path(facts, path, resolution.value)
            missing.discard(path)
            used.extend(resolution.fact_ids)
            unit = resolution.facts[0].unit
            if unit is not None:
                units[path] = unit
    if units:
        facts["fact_units"] = units
    return facts, sorted(set(used)), sorted(missing)


def _record_evidence(record: dict[str, Any], retrieved_at: datetime) -> Evidence:
    digest = canonical_digest(record)
    return Evidence(
        evidence_id=f"land:{digest[:16]}",
        source=SourceRef(
            provider="korean-land-mcp",
            contract=LAND_CONTRACT,
            retrieved_at=retrieved_at,
            query={"query": record.get("query")},
        ),
        snapshot_hash=digest,
        locator={"tool": "analyze_parcel"},
    )


def facts_from_land_record(
    record: dict[str, Any],
    retrieved_at: datetime,
    *,
    subject: str | None = None,
) -> tuple[list[Fact], Evidence]:
    """Wrap one ``analyze_parcel`` record as facts with ``korean-land-parcel-analysis/2`` meaning.

    Absence means nothing unless the query was complete: with point precision or a layer error
    ``designation.query_complete`` stays UNKNOWN (S03), and 지목 never decides the legal status of
    farmland or mountain land.
    """

    parcel = record.get("parcel") or {}
    name = subject or parcel.get("pnu") or "site"
    evidence = _record_evidence(record, retrieved_at)
    source = record.get("source") or {}
    precision = source.get("precision")
    errors = record.get("layer_errors") or []
    validity = Interval(valid_from=retrieved_at.date())
    facts: list[Fact] = []

    def emit(path: str, value: Any, note: str | None = None) -> None:
        facts.append(
            Fact(
                fact_id=f"{evidence.evidence_id}:{name}:{path}",
                path=path,
                subject=name,
                value=value,
                status=FactStatus.UNKNOWN if value is None else FactStatus.OBSERVED,
                method="official_record",
                validity=validity,
                recorded_at=retrieved_at,
                evidence_ids=[evidence.evidence_id],
                note=note,
            )
        )

    emit("land.jimok", parcel.get("jimok"))
    emit("land.is_mountain_register", parcel.get("is_mountain_register"))
    emit("land.precision", precision)
    for path in LEGAL_STATUS_PATHS:
        emit(path, None, "legal status is not derived from the land register category")

    note = None
    if precision != "polygon":
        note = f"precision={precision}: a miss is not a negative check"
    elif errors:
        note = "layer errors: " + ", ".join(sorted(str(e.get("layer")) for e in errors))

    zoning = record.get("zoning") or {}
    hits = [
        *(hit for group in zoning.values() if isinstance(group, list) for hit in group),
        *(record.get("district_plan") or []),
        *(record.get("urban_facility") or []),
    ]
    seen: set[str] = set()
    for hit in hits:
        layer = hit.get("layer")
        if layer and layer not in seen:
            seen.add(layer)
            emit(f"designation.{layer}", True, note)
    emit("designation.query_complete", True if note is None else None, note)
    return facts, evidence
