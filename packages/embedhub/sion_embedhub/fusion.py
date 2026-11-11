"""Cross-space fusion. Scores from different embedding spaces are NOT comparable,
so results are combined by rank (Reciprocal Rank Fusion), never by raw similarity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def rrf(rankings: Mapping[str, Sequence[str]], k: int = 60, weights: Mapping[str, float] | None = None) -> list[tuple[str, float]]:
    """rankings: {source_name: [item_id best-first]} -> [(item_id, score)] best-first."""
    scores: dict[str, float] = {}
    for name, ranked in rankings.items():
        w = (weights or {}).get(name, 1.0)
        seen = set()
        for pos, item in enumerate(ranked, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + w / (k + pos)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def agreement(rankings: Mapping[str, Sequence[str]], top: int = 5) -> dict:
    """How much independent retrievers (e.g. text vs image space) agree on the top-N.

    Returns the intersection of all top-N lists, the pairwise Jaccard mean, and a
    verdict: ``confirmed`` (top-1 shared), ``partial`` (overlap but top-1 differs),
    ``conflict`` (no overlap -> send to a human)."""
    tops = {n: list(r[:top]) for n, r in rankings.items() if r}
    if len(tops) < 2:
        return {"verdict": "single_source", "common": [], "jaccard": None, "top1": {n: t[0] for n, t in tops.items()}}
    sets = [set(t) for t in tops.values()]
    common = set.intersection(*sets)
    pairs = [(a, b) for i, a in enumerate(sets) for b in sets[i + 1:]]
    jac = sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)
    top1s = {t[0] for t in tops.values()}
    if len(top1s) == 1:
        verdict = "confirmed"
    elif common or jac > 0:
        verdict = "partial"
    else:
        verdict = "conflict"
    return {"verdict": verdict, "common": sorted(common), "jaccard": round(jac, 4), "top1": {n: t[0] for n, t in tops.items()}}
