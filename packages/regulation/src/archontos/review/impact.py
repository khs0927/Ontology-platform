"""Change impact (W13; S28). A change opens a re-review; it never edits an old report."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from archontos.review.model import LegalVersion, Provision, canonical_digest

ChangeKind = Literal["none", "hash_only", "text", "effectivity"]


@dataclass(frozen=True, slots=True)
class ProvisionChange:
    provision_key: str
    kind: ChangeKind
    new_provision_key: str | None = None


@dataclass(frozen=True, slots=True)
class ImpactRecord:
    """Re-review request for one saved work. ``blocking`` False: only source metadata moved."""

    task_id: str
    work_id: str
    work_revision: str
    provision_key: str
    change_kind: ChangeKind
    rule_version_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]
    blocking: bool


def classify_change(
    old: Provision,
    new: Provision,
    *,
    old_version: LegalVersion | None = None,
    new_version: LegalVersion | None = None,
) -> ProvisionChange:
    """Tell a metadata-only move from a real change of text or effect."""

    kind: ChangeKind = "none"
    if old.text != new.text:
        kind = "text"
    elif old_version and new_version and old_version.effective != new_version.effective:
        kind = "effectivity"
    elif old.evidence_id != new.evidence_id:
        kind = "hash_only"
    elif old_version and new_version and old_version.snapshot_hash != new_version.snapshot_hash:
        kind = "hash_only"
    return ProvisionChange(old.ref.key, kind, new.ref.key)


@dataclass(slots=True)
class ImpactGraph:
    """Edges provision version -> rule version -> evaluation -> saved work revision."""

    _rules: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _evaluations: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _works: dict[str, set[tuple[str, str]]] = field(default_factory=lambda: defaultdict(set))

    def link_rule(self, provision_key: str, rule_version_id: str) -> None:
        self._rules[provision_key].add(rule_version_id)

    def link_evaluation(self, rule_version_id: str, evaluation_id: str) -> None:
        self._evaluations[rule_version_id].add(evaluation_id)

    def link_work(self, evaluation_id: str, work_id: str, work_revision: str) -> None:
        self._works[evaluation_id].add((work_id, work_revision))

    def impacted_works(self, change: ProvisionChange) -> list[ImpactRecord]:
        if change.kind == "none":
            return []
        evaluations_by_work: dict[tuple[str, str], set[str]] = defaultdict(set)
        rules_by_work: dict[tuple[str, str], set[str]] = defaultdict(set)
        for rule in sorted(self._rules.get(change.provision_key, set())):
            for evaluation in self._evaluations.get(rule, set()):
                for work in self._works.get(evaluation, set()):
                    evaluations_by_work[work].add(evaluation)
                    rules_by_work[work].add(rule)
        return [
            ImpactRecord(
                task_id="impact:" + canonical_digest([change.provision_key, work])[:16],
                work_id=work[0],
                work_revision=work[1],
                provision_key=change.provision_key,
                change_kind=change.kind,
                rule_version_ids=tuple(sorted(rules_by_work[work])),
                evaluation_ids=tuple(sorted(evaluations_by_work[work])),
                blocking=change.kind != "hash_only",
            )
            for work in sorted(evaluations_by_work)
        ]
