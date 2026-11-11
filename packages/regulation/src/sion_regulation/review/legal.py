"""Versioned legal catalog and reference resolution (W06; scenarios S11, S14, S15, S16).

A law is identified by its persistent ``work_id`` and each text by its ``version_id``. Titles are
never identity: two works may share a title (S15) and a renamed work keeps its ``work_id``.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sion_regulation.review.model import LegalVersion, Provision, ProvisionRef

_ARTICLE = re.compile(
    r"^제(?P<article>\d+)조(?:의(?P<branch>\d+))?"
    r"(?:제(?P<paragraph>\d+)항)?"
    r"(?:제(?P<item>\d+)호(?:의(?P<item_branch>\d+))?)?"
    r"(?:(?P<sub_item>[가-힣])목)?$"
)
_ANNEX = re.compile(r"^별표(?P<annex_no>\d+(?:의\d+)?)$")
_ADDENDUM = re.compile(r"^부칙(?:\s+(?P<addendum_key>.+))?$")


def parse_article_label(label: str) -> dict[str, Any]:
    """Parse a Korean provision label into ``ProvisionRef`` position fields.

    Raises ``ValueError`` for anything it cannot read exactly: a partly understood label must not
    silently point at a broader provision.
    """

    text = re.sub(r"\s+", "", label)
    if match := _ARTICLE.match(text):
        parsed: dict[str, Any] = {"kind": "article"}
        for name in ("article", "branch", "paragraph", "item", "item_branch"):
            if match[name] is not None:
                parsed[name] = int(match[name])
        if match["sub_item"] is not None:
            parsed["sub_item"] = match["sub_item"]
        return parsed
    if match := _ANNEX.match(text):
        return {"kind": "annex", "annex_no": match["annex_no"]}
    if match := _ADDENDUM.match(label.strip()):
        parsed = {"kind": "addendum"}
        if match["addendum_key"]:
            parsed["addendum_key"] = match["addendum_key"].strip()
        return parsed
    raise ValueError(f"unrecognised provision label: {label!r}")


def verify_returned_provision(requested: ProvisionRef, returned: Provision) -> str | None:
    """Return the mismatch reason when a provider answered with another provision (S16)."""

    if requested.key == returned.ref.key:
        return None
    differing = [
        name
        for name in ProvisionRef.model_fields
        if getattr(requested, name) != getattr(returned.ref, name)
    ]
    return f"returned provision differs from request in: {', '.join(differing)}"


@dataclass(frozen=True, slots=True)
class VersionResolution:
    """Outcome of a point-in-time lookup; ``version`` is ``None`` unless exactly one matched."""

    version: LegalVersion | None
    reason: str | None = None


@dataclass(slots=True)
class ReferenceExpansion:
    visited: list[str] = field(default_factory=list)
    provisions: list[Provision] = field(default_factory=list)
    unresolved: list[ProvisionRef] = field(default_factory=list)
    depth_capped: bool = False
    capped_refs: list[ProvisionRef] = field(default_factory=list)


class LegalCatalog:
    """In-memory catalog. New text is added as a new version, never written over an old one."""

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, LegalVersion]] = {}
        self._provisions: dict[str, Provision] = {}

    def add_version(self, version: LegalVersion) -> None:
        versions = self._versions.setdefault(version.work_id, {})
        existing = versions.get(version.version_id)
        if existing is not None and existing != version:
            raise ValueError(f"version {version.version_id} already exists with other content")
        versions[version.version_id] = version

    def add_provision(self, provision: Provision) -> None:
        ref = provision.ref
        if ref.version_id not in self._versions.get(ref.work_id, {}):
            raise ValueError(f"unknown law version for provision: {ref.key}")
        existing = self._provisions.get(ref.key)
        if existing is not None and existing != provision:
            raise ValueError(f"provision {ref.key} already exists with other content")
        self._provisions[ref.key] = provision

    def version(self, work_id: str, version_id: str) -> LegalVersion | None:
        return self._versions.get(work_id, {}).get(version_id)

    def lineage(self, work_id: str) -> list[LegalVersion]:
        """All versions of a work, oldest first; undated versions sort first."""

        return sorted(
            self._versions.get(work_id, {}).values(),
            key=lambda v: (v.effective.valid_from or date.min, v.version_id),
        )

    def resolve_version(self, work_id: str, day: date) -> VersionResolution:
        versions = self.lineage(work_id)
        if not versions:
            return VersionResolution(None, f"no versions known for {work_id}")
        decisions = [(version, version.effective.contains(day)) for version in versions]
        undecided = [version for version, decided in decisions if decided is None]
        matches = [version for version, decided in decisions if decided is True]
        if undecided:
            ids = ", ".join(version.version_id for version in undecided)
            return VersionResolution(None, f"effective start unknown for {ids}")
        if len(matches) > 1:
            ids = ", ".join(version.version_id for version in matches)
            return VersionResolution(None, f"overlapping versions on {day}: {ids}")
        if not matches:
            return VersionResolution(None, f"no version of {work_id} effective on {day}")
        return VersionResolution(matches[0])

    def version_at(self, work_id: str, day: date) -> LegalVersion | None:
        """The single version in force on ``day``; ``None`` when absent or ambiguous."""

        return self.resolve_version(work_id, day).version

    def get(self, ref: ProvisionRef) -> Provision | None:
        return self._provisions.get(ref.key)

    def provisions(self) -> list[Provision]:
        return [self._provisions[key] for key in sorted(self._provisions)]


def expand_references(
    catalog: LegalCatalog, roots: list[ProvisionRef], max_depth: int
) -> ReferenceExpansion:
    """Breadth-first closure of provision references.

    ``seen`` is keyed by version-bound provision, so a cycle terminates and each provision is kept
    once (S14). A reference beyond ``max_depth`` is reported, not dropped.
    """

    result = ReferenceExpansion()
    seen: set[str] = set()
    capped: dict[str, ProvisionRef] = {}
    queue: deque[tuple[ProvisionRef, int]] = deque((root, 0) for root in roots)
    while queue:
        ref, depth = queue.popleft()
        if ref.key in seen:
            continue
        if depth > max_depth:
            capped.setdefault(ref.key, ref)
            continue
        seen.add(ref.key)
        provision = catalog.get(ref)
        if provision is None:
            result.unresolved.append(ref)
            continue
        result.visited.append(ref.key)
        result.provisions.append(provision)
        queue.extend((target, depth + 1) for target in provision.references)
    result.capped_refs = [ref for key, ref in capped.items() if key not in seen]
    result.depth_capped = bool(result.capped_refs)
    return result
