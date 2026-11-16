"""Bitemporal fact store (W05; scenarios S02, S03, S12, S13, S17, S21, S22).

``validity`` is when a fact holds in the world, ``recorded_at``/``superseded_at`` is when this
system believed it. Nothing is deleted: a correction closes the old row and adds a new one. A
missing, partial or conflicting value stays unknown; it is never turned into ``False``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sion_regulation.review.model import (
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

# Methods a caller may use for its own statements (section 16): project input claims.
CLAIM_METHODS = frozenset({"user_claim", "design_observed"})
# Paths that only server-side collection may resolve: designations, legal status, collected
# documents, query completeness and the official land-register values of LAND_CONTRACT.
COLLECTION_ONLY_PREFIXES = ("designation.", "legal.", "document.")
COLLECTION_ONLY_PATHS = frozenset({"land.jimok", "land.is_mountain_register", "land.precision"})


# Keys the workflow or the rule engine write into rule input themselves; no fact may set them.
# ``rase`` holds the engine-side exception override (rase.exempted, see rase.py).
RESERVED_ROOTS = frozenset({"fact_units", "context", "rase"})
_CANONICAL_PATH = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*")


def canonical_path(path: str) -> bool:
    """A caller may name only lower-case dotted identifiers outside the reserved roots."""

    return bool(_CANONICAL_PATH.fullmatch(path)) and _root(path) not in RESERVED_ROOTS


def _root(path: str) -> str:
    return path.split(".", 1)[0]


def collection_only(path: str) -> bool:
    """True when ``path`` may be resolved only by collected facts with evidence.

    A parent of a collection-only prefix or path (``legal``, ``designation``, ``document``,
    ``land``) counts as well: a mapping value there would write the reserved leaves into rule
    input. The comparison ignores case and surrounding blanks, so a variant spelling of a
    reserved path is never left to a claim.
    """

    path = path.strip().lower()
    parent = path + "."
    if any(p.startswith(parent) for p in (*COLLECTION_ONLY_PREFIXES, *COLLECTION_ONLY_PATHS)):
        return True
    return (
        path.startswith(COLLECTION_ONLY_PREFIXES)
        or path.endswith(".query_complete")
        or path == "query_complete"
        or path in COLLECTION_ONLY_PATHS
    )


def is_claim(fact: Fact) -> bool:
    """A caller's statement: it never carries the weight of an official record."""

    return fact.method in CLAIM_METHODS


def is_collected(fact: Fact) -> bool:
    """A server-side fact that cites evidence."""

    return not is_claim(fact) and bool(fact.evidence_ids)


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

    @property
    def evidenced(self) -> bool:
        """Known, and backed by at least one collected fact with evidence (no claim alone)."""

        return self.known and any(is_collected(fact) for fact in self.facts)


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
        if collection_only(path):
            # Defence in depth: a claim never resolves a collection-only path.
            believed = [f for f in believed if not is_claim(f)]
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

        # Collected facts first, so an agreeing claim never sets the resolved status.
        valued = sorted(
            (fact for fact in in_force if fact.status is not FactStatus.UNKNOWN), key=is_claim
        )
        if not valued:
            return FactResolution(
                FactStatus.UNKNOWN, facts=tuple(in_force), reason=in_force[0].note
            )
        open_records = [f for f in in_force if f.status is FactStatus.UNKNOWN and not is_claim(f)]
        if open_records and all(is_claim(fact) for fact in valued):
            # A collected "unknown" (point precision, layer error, not derivable) is not filled
            # by a lower-provenance claim (S03, section 6).
            return FactResolution(
                FactStatus.UNKNOWN,
                facts=tuple(open_records),
                reason=open_records[0].note or "collected value unknown; a claim does not fill it",
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
    accept: Callable[[str, Fact], bool] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build rule-engine input as ``(facts, used_fact_ids, missing_paths)``.

    Unknown, disputed and partly observed values are omitted, so the fail-closed rule engine
    answers REVIEW instead of comparing against a guess (S13, S22). Subjects are not merged: a
    path recorded for more than one subject (e.g. the parcel and the project) is ambiguous and
    omitted rather than decided by whichever subject came last. ``accept`` can refuse a fact for
    a path (rule fact bindings); a path with any refused fact is omitted as well.

    Guards and bindings are keyed by exact leaf paths, so a fact must never write leaves through
    a parent: a path that is a prefix of another recorded path (``land`` next to ``land.slope``),
    a reserved root (``fact_units``, ``context``) and a mapping value stated by a claim are all
    treated as missing.
    """

    subjects = list(dict.fromkeys([subject] if isinstance(subject, str) else subject))
    owners: dict[str, list[str]] = {}
    for name in subjects:
        for path in store.paths(name):
            owners.setdefault(path, []).append(name)
    facts: dict[str, Any] = {}
    units: dict[str, str] = {}
    used: list[str] = []
    missing: set[str] = set(required)
    for path, names in sorted(owners.items()):
        if len(names) > 1:
            missing.add(path)  # same path from two subjects: never last-write-wins
            continue
        nested = any(
            other.startswith(path + ".") or path.startswith(other + ".") for other in owners
        )
        if nested or _root(path) in RESERVED_ROOTS:
            missing.add(path)  # overlapping owners or a workflow-owned key: never merged
            continue
        resolution = store.current(path, names[0], day, as_of_recorded)
        partial = any(fact.observation_scope != "whole" for fact in resolution.facts)
        refused = accept is not None and any(not accept(path, f) for f in resolution.facts)
        claimed_mapping = isinstance(resolution.value, Mapping) and any(
            is_claim(fact) for fact in resolution.facts
        )
        if not resolution.known or partial or refused or claimed_mapping:
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
