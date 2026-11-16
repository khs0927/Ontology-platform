"""Gold set: questions with the corpus keys a correct retrieval must return."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .corpus import ROOT, Doc

DEFAULT_GOLDSET = ROOT / "data" / "eval" / "building-law-gold.v1.jsonl"
CATEGORIES = {"single", "cross", "numeric", "as_of"}


@dataclass(frozen=True)
class GoldQuery:
    id: str
    query: str
    category: str
    relevant: tuple[str, ...]
    as_of: str | None = None


def load_goldset(path: Path | str = DEFAULT_GOLDSET) -> list[GoldQuery]:
    out: list[GoldQuery] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out.append(GoldQuery(row["id"], row["query"], row["category"], tuple(row["relevant"]), row.get("as_of")))
    return out


def validate_goldset(gold: list[GoldQuery], corpus: list[Doc]) -> list[str]:
    """Return problems; an empty list means every query is answerable from the corpus."""
    keys = {d.key for d in corpus}
    problems: list[str] = []
    ids = [q.id for q in gold]
    if len(ids) != len(set(ids)):
        problems.append("duplicate query ids")
    for q in gold:
        if not q.query.strip():
            problems.append(f"{q.id}: empty query")
        if q.category not in CATEGORIES:
            problems.append(f"{q.id}: unknown category {q.category!r}")
        if not q.relevant:
            problems.append(f"{q.id}: no relevant keys")
        problems += [f"{q.id}: {k} not in corpus" for k in q.relevant if k not in keys]
    return problems
