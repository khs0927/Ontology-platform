"""Baseline retrievers. Each returns ranked corpus keys for a query.

* ``bm25-word``   Okapi BM25 over whitespace/regex word tokens (no Korean morphology).
* ``bm25-bigram`` Okapi BM25 over word tokens plus Hangul character bigrams, a dictionary-free
                  way to match Korean stems inside inflected words ("건폐율은" -> "건폐", "폐율").
* ``law-search``  the production lexical search, ``sion_api.law_knowledge.search``, run in-process
                  on an in-memory SQLite copy of the corpus.

Later phases (morphological BM25, vectors, graph expansion, reranking) register here and are
compared on the same gold set.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable

from .corpus import Doc

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL = re.compile(r"[가-힣]{2,}")


def word_tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(unicodedata.normalize("NFC", text or ""))]


def bigram_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text or "")
    out = word_tokens(text)
    for run in _HANGUL.findall(text):
        out += [run[i:i + 2] for i in range(len(run) - 1)]
    return out


class Bm25:
    def __init__(self, docs: list[Doc], tokenize: Callable[[str], list[str]], *, k1: float = 1.2, b: float = 0.75):
        self.keys = [d.key for d in docs]
        self.tokenize = tokenize
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(f"{d.law_name} {d.title or ''} {d.text}")) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def __call__(self, query: str, k: int) -> list[str]:
        q = set(self.tokenize(query))
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: (-x[0], self.keys[x[1]]))
        return [self.keys[i] for _, i in scores[:k]]


def law_search_retriever(docs: list[Doc]) -> Callable[[str, int], list[str]]:
    """The API's lexical law search over an in-memory SQLite copy of the corpus."""
    from datetime import date

    from fastapi import HTTPException
    from sion_api.law_knowledge import LawArticle, LawArticleIn, ingest, search
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    LawArticle.__table__.create(engine)
    with Session(engine) as session:
        # The corpus has no effective dates; one fixed date keeps every article "in force".
        items = [LawArticleIn(law_id=d.law_name, law_name=d.law_name, law_kind=d.law_kind, article_key=d.article_key,
                              title=d.title, text=d.text, effective_from=date(2000, 1, 1)) for d in docs]
        ingest(session, items)

    def retrieve(query: str, k: int) -> list[str]:
        with Session(engine) as session:
            try:
                res = search(session, query, limit=k, as_of=date(2026, 1, 1))
            except HTTPException:
                return []
        return [f"{r['law_name']}:{r['article_key']}" for r in res["results"]]

    return retrieve


RETRIEVERS: dict[str, Callable[[list[Doc]], Callable[[str, int], list[str]]]] = {
    "bm25-word": lambda docs: Bm25(docs, word_tokens),
    "bm25-bigram": lambda docs: Bm25(docs, bigram_tokens),
    "law-search": law_search_retriever,
}
