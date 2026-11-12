"""Ranking metrics. Every query has a set of relevant keys; a run is a ranked key list per query."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from .goldset import GoldQuery

Retrieve = Callable[[str, int], list[str]]


def recall_at(ranked: list[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    return len(rel & set(ranked[:k])) / len(rel) if rel else 0.0


def hit_at(ranked: list[str], relevant: Iterable[str], k: int) -> float:
    return 1.0 if set(relevant) & set(ranked[:k]) else 0.0


def reciprocal_rank(ranked: list[str], relevant: Iterable[str]) -> float:
    rel = set(relevant)
    return next((1.0 / i for i, key in enumerate(ranked, 1) if key in rel), 0.0)


def ndcg_at(ranked: list[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    dcg = sum(1.0 / math.log2(i + 1) for i, key in enumerate(ranked[:k], 1) if key in rel)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(rel), k) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate(gold: list[GoldQuery], retrieve: Retrieve, *, k: int = 10) -> list[dict]:
    rows = []
    for q in gold:
        ranked = list(dict.fromkeys(retrieve(q.query, k)))[:k]  # de-duplicate, keep order
        rows.append({
            "id": q.id, "category": q.category, "relevant": list(q.relevant), "ranked": ranked,
            "hit@1": hit_at(ranked, q.relevant, 1), "hit@5": hit_at(ranked, q.relevant, 5),
            "recall@5": recall_at(ranked, q.relevant, 5), f"recall@{k}": recall_at(ranked, q.relevant, k),
            "mrr": reciprocal_rank(ranked, q.relevant), f"ndcg@{k}": ndcg_at(ranked, q.relevant, k),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    metrics = [m for m in rows[0] if m not in {"id", "category", "relevant", "ranked"}] if rows else []

    def mean(sub: list[dict]) -> dict:
        return {"n": len(sub), **{m: round(sum(r[m] for r in sub) / len(sub), 4) for m in metrics}}

    by_cat = {}
    for cat in sorted({r["category"] for r in rows}):
        by_cat[cat] = mean([r for r in rows if r["category"] == cat])
    return {"overall": mean(rows) if rows else {"n": 0}, "by_category": by_cat}
