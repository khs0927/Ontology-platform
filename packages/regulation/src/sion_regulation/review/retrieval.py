"""Scoped evidence retrieval (W11; scenarios S23, S24, S25, S30).

Order follows section 11: restrict by project, date and jurisdiction first, match official
identifiers exactly, follow allowed reference paths, then let an optional search hook add context.
Required provisions are always included, so a similarity cut-off can never drop them. The hook is
optional: without it, or when it fails, the deterministic result still stands.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sion_regulation.review.legal import LegalCatalog, expand_references, parse_article_label
from sion_regulation.review.model import Evidence, Provision, ProvisionRef

Search = Callable[[str], Sequence[str]]  # returns provision keys, best first

_LABEL = re.compile(
    r"제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호(?:의\d+)?)?(?:[가-힣]목)?|별표\s*\d+(?:의\d+)?"
)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    project_id: str | None
    as_of: date
    jurisdiction_code: str | None = None


@dataclass(slots=True)
class RetrievalResult:
    provisions: list[Provision] = field(default_factory=list)
    required_keys: list[str] = field(default_factory=list)
    unresolved_required: list[str] = field(default_factory=list)
    filtered_out: int = 0
    degraded: str | None = None


def visible(evidence: Evidence, project_id: str | None) -> bool:
    return evidence.public or evidence.project_id == project_id


def _in_scope(
    provision: Provision,
    scope: RetrievalScope,
    catalog: LegalCatalog,
    evidence: Mapping[str, Evidence],
) -> bool:
    version = catalog.version(provision.ref.work_id, provision.ref.version_id)
    if version is None or version.effective.contains(scope.as_of) is not True:
        return False
    local = version.jurisdiction_code
    if local is not None and local != scope.jurisdiction_code:
        return False
    if provision.evidence_id is None:
        return True
    item = evidence.get(provision.evidence_id)
    return item is not None and visible(item, scope.project_id)


def _matches_label(provision: Provision, parsed: dict[str, object]) -> bool:
    return all(getattr(provision.ref, name) == value for name, value in parsed.items())


def retrieve(
    question: str,
    scope: RetrievalScope,
    catalog: LegalCatalog,
    evidence: Mapping[str, Evidence],
    required: Sequence[ProvisionRef] = (),
    *,
    search: Search | None = None,
    limit: int = 20,
    max_depth: int = 2,
) -> RetrievalResult:
    pool = [p for p in catalog.provisions() if _in_scope(p, scope, catalog, evidence)]
    allowed = {provision.ref.key: provision for provision in pool}
    result = RetrievalResult(filtered_out=len(catalog.provisions()) - len(pool))

    chosen: dict[str, Provision] = {}
    for ref in required:
        result.required_keys.append(ref.key)
        provision = allowed.get(ref.key)
        if provision is None:
            result.unresolved_required.append(ref.key)
        else:
            chosen[ref.key] = provision

    labels = [parse_article_label(label) for label in _LABEL.findall(question)]
    exact = [p for p in pool for parsed in labels if _matches_label(p, parsed)]
    for provision in exact:
        chosen.setdefault(provision.ref.key, provision)

    roots = [provision.ref for provision in chosen.values()]
    for provision in expand_references(catalog, roots, max_depth).provisions:
        if provision.ref.key in allowed:
            chosen.setdefault(provision.ref.key, provision)

    if search is not None:
        try:
            hits = list(search(question))
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            result.degraded = f"search unavailable: {type(exc).__name__}"
            hits = []
        for key in hits:
            provision = allowed.get(key)  # a hit outside the scope is discarded here too
            if provision is not None and len(chosen) < max(limit, len(result.required_keys)):
                chosen.setdefault(key, provision)
    result.provisions = list(chosen.values())
    return result
