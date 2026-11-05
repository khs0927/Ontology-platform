"""Citation verification (W11; S23). An unverifiable claim is removed from the briefing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from archontos.review.model import Citation, Evidence, Provision


def verify_citations(
    citations: Sequence[Citation],
    evidence_index: Mapping[str, Evidence],
    provisions: Mapping[str, Provision],
    *,
    project_id: str | None = None,
) -> list[Citation]:
    """Return copies with ``verified`` and ``failure`` set from real evidence.

    The incoming ``verified`` flag is ignored: a caller cannot vouch for itself. Each cited
    evidence id must exist and be visible to ``project_id``, the provision must exist and tie to
    that evidence, and the evidence excerpt must really be in the provision text.
    """

    checked: list[Citation] = []
    for citation in citations:
        failure = _failure(citation, evidence_index, provisions, project_id)
        checked.append(
            citation.model_copy(update={"verified": failure is None, "failure": failure})
        )
    return checked


def _failure(
    citation: Citation,
    evidence_index: Mapping[str, Evidence],
    provisions: Mapping[str, Provision],
    project_id: str | None,
) -> str | None:
    evidence: list[Evidence] = []
    for evidence_id in citation.evidence_ids:
        item = evidence_index.get(evidence_id)
        if item is None:
            return f"unknown evidence id: {evidence_id}"
        if not item.public and item.project_id != project_id:
            return f"evidence not visible to this project: {evidence_id}"
        evidence.append(item)
    if citation.provision_key is None:
        return None
    provision = provisions.get(citation.provision_key)
    if provision is None:
        return f"unknown provision: {citation.provision_key}"
    linked = [item for item in evidence if item.evidence_id == provision.evidence_id]
    if not linked:
        return "cited evidence does not belong to the provision"
    if any(item.excerpt.strip() not in provision.text for item in linked if item.excerpt):
        return "evidence excerpt not found in provision text"
    return None


def drop_unverified(citations: Sequence[Citation]) -> list[Citation]:
    return [citation for citation in citations if citation.verified]
