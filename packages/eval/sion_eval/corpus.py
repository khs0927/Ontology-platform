"""Statute corpus: one document per article, keyed ``<law name>:<article key>`` (e.g. ``건축법:61-2``)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = ROOT / "data" / "eval" / "law-corpus.v1.jsonl.gz"


@dataclass(frozen=True)
class Doc:
    law_name: str
    article_key: str  # "61" or "61-2" (제61조의2), the sion_api.law_knowledge format
    title: str | None
    text: str

    @property
    def key(self) -> str:
        return f"{self.law_name}:{self.article_key}"

    @property
    def law_kind(self) -> str:
        if self.law_name.endswith("시행령"):
            return "decree"
        if self.law_name.endswith("시행규칙"):
            return "rule"
        return "act"


def load_law_corpus(path: Path | str = DEFAULT_CORPUS) -> list[Doc]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    docs: list[Doc] = []
    seen: set[str] = set()
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            doc = Doc(row["law_name"], row["article_key"], row.get("title"), row["text"])
            if doc.key in seen:
                raise ValueError(f"duplicate corpus key {doc.key}")
            seen.add(doc.key)
            docs.append(doc)
    return docs
