"""Hybrid law-article search: Korean BM25 + optional vectors + citation-graph expansion, fused by RRF.

Channels (each yields a ranking of article keys ``"<법령명>:<article_key>"``; only versions in force
on ``as_of`` take part, newest version per article):

* **bm25**   Okapi BM25 over word tokens plus Hangul character bigrams. Bigrams match stems inside
             inflected Korean words ("건폐율은" -> "건폐", "폐율") without a morphological
             dictionary; on the building-law gold set they lift recall@10 from 0.716 (words only) to
             0.977 (``docs/EVALUATION.md``).
* **vector** cosine similarity of query and article embeddings, when an embedder is configured
             (``SION_LAW_EMBED_MODEL``: an EmbedHub model key such as a KURE or Qwen3-Embedding
             entry). Article vectors are cached per (model, content_hash).
* **graph**  articles cited by the top fused hits (``law_articles.refs``, slice 3) are lifted to
             just below their citer (see :func:`_graph_expand`). "건폐율 최대한도" finds 건축법 제55조 lexically and
             국토계획법 제77조 through its citation.

The bm25 and vector rankings are combined with Reciprocal Rank Fusion
(``sion_embedhub.fusion.rrf``): scores from different channels are not comparable, ranks are.
Graph expansion then works on the fused scores; it is not a third RRF list, because RRF adds
scores and would rank a cited article above the article that cites it. Every result says which
channels found it (``channels.graph`` names the citing article).

The BM25 index is built in process from the table and cached until the table changes; it is
portable across SQLite and PostgreSQL and sized for the curated corpus (about 10^4 articles).
Past roughly 10^5 articles the lexical channel should move into the database (PGroonga or a
tokenised ``tsvector`` column) behind the same interface.
"""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .law_knowledge import LawArticle, article_label

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL = re.compile(r"[가-힣]{2,}")
CHANNEL_DEPTH = 50
GRAPH_SEEDS = 3
GRAPH_UNMATCHED_PER_SEED = 0
WEIGHTS = {"bm25": 1.0, "vector": 1.0}

Embedder = Callable[[Sequence[str], str], list[list[float]]]  # (texts, role) -> vectors


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text or "")
    out = [t.lower() for t in _WORD.findall(text)]
    for run in _HANGUL.findall(text):
        out += [run[i:i + 2] for i in range(len(run) - 1)]
    return out


def article_key(a: LawArticle) -> str:
    return f"{a.law_name}:{a.article_key}"


# --------------------------------------------------------------------------- BM25 index


class Bm25Index:
    def __init__(self, rows: Sequence[LawArticle], *, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf: dict[str, Counter] = {}
        for a in rows:  # one entry per row id: versions are filtered at query time
            self.tf[str(a.id)] = Counter(tokens(f"{a.law_name} {a.title or ''} {a.text}"))
        self.length = {i: sum(c.values()) for i, c in self.tf.items()}
        self.avg = sum(self.length.values()) / max(len(self.length), 1)
        df: Counter = Counter()
        for c in self.tf.values():
            df.update(c.keys())
        n = len(self.tf)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def rank(self, query: str, row_ids: Sequence[str], depth: int) -> list[tuple[str, float]]:
        q = [t for t in set(tokens(query)) if t in self.idf]
        scored = []
        for i in row_ids:
            tf = self.tf.get(i)
            if not tf:
                continue
            norm = self.k1 * (1 - self.b + self.b * self.length[i] / self.avg)
            s = sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in q if t in tf)
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:depth]


_cache_lock = threading.Lock()
_index_cache: dict[tuple, Bm25Index] = {}
_vector_cache: dict[tuple[str, str], list[float]] = {}


def _index(session: Session) -> Bm25Index:
    count, latest = session.execute(select(func.count(LawArticle.id), func.max(LawArticle.ingested_at))).one()
    bind = session.get_bind()
    stamp = (id(bind), str(bind.url), count, str(latest))
    with _cache_lock:
        index = _index_cache.get(stamp)
    if index is None:
        index = Bm25Index(list(session.scalars(select(LawArticle))))
        with _cache_lock:
            _index_cache.clear()  # one live table per process is the normal case
            _index_cache[stamp] = index
    return index


# --------------------------------------------------------------------------- channels


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _vector_rank(query: str, rows: Sequence[LawArticle], embedder: Embedder, model: str, depth: int) -> list[str]:
    missing = [a for a in rows if (model, a.content_hash) not in _vector_cache]
    for start in range(0, len(missing), 64):
        batch = missing[start:start + 64]
        vectors = embedder([f"{a.law_name} {article_label(a.article_key)} {a.title or ''}\n{a.text}" for a in batch],
                           "passage")
        for a, v in zip(batch, vectors):
            _vector_cache[(model, a.content_hash)] = v
    q = embedder([query], "query")[0]
    scored = sorted(((article_key(a), _cosine(q, _vector_cache[(model, a.content_hash)])) for a in rows),
                    key=lambda x: -x[1])
    return [k for k, s in scored[:depth] if s > 0]


def _graph_expand(fused: list[tuple[str, float]], in_force: dict[str, LawArticle], candidates: dict[str, LawArticle],
                  *, seeds: int, unmatched_per_seed: int) -> tuple[list[tuple[str, float]], dict[str, str]]:
    """Lift the articles cited by the top hits to just below the hit that cites them.

    "건폐율 최대한도" finds 건축법 제55조 lexically; 제55조 cites 국토계획법 제77조, which the
    question needs too, so 제77조 moves up to sit right after 제55조. A cited article that the
    other channels also matched is always lifted; up to ``unmatched_per_seed`` cited articles with
    no lexical/vector match are added as well (the citation is the only evidence). Only outgoing
    citations are followed: incoming ones fan out (건축법 제2조 is cited by hundreds).
    """
    scores = dict(fused)
    via: dict[str, str] = {}
    for seed, seed_score in fused[:seeds]:
        article = in_force.get(seed)
        added = 0
        for ref in (article.refs or []) if article else []:
            if ref not in candidates or ref == seed:
                continue
            matched = ref in scores
            if not matched:
                if added >= unmatched_per_seed:
                    continue
                added += 1
            lifted = seed_score * (1 - 1e-4 * (len(via) + 1))  # just below the citer, citation order kept
            if lifted > scores.get(ref, 0.0):
                scores[ref] = lifted
                via[ref] = seed
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])), via


# --------------------------------------------------------------------------- search


@dataclass
class HybridOptions:
    embedder: Embedder | None = None
    embed_model: str | None = None
    graph: bool = True
    depth: int = CHANNEL_DEPTH


def _snippet(text: str, query: str, width: int = 200) -> str:
    low = text.lower()
    hits = [low.find(t) for t in tokens(query) if len(t) > 1 and low.find(t) >= 0]
    pos = min(hits, default=0)
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width] + ("…" if start + width < len(text) else "")


def hybrid_search(session: Session, q: str, *, law: str | None = None, as_of: date | None = None, limit: int = 10,
                  options: HybridOptions | None = None) -> dict:
    from sion_embedhub.fusion import rrf

    options = options or HybridOptions()
    as_of = as_of or date.today()
    stmt = select(LawArticle).where(LawArticle.effective_from <= as_of,
                                    (LawArticle.effective_to.is_(None)) | (LawArticle.effective_to >= as_of))
    in_force: dict[str, LawArticle] = {}
    for a in session.scalars(stmt):
        k = article_key(a)
        if k not in in_force or a.effective_from > in_force[k].effective_from:
            in_force[k] = a
    candidates = {k: a for k, a in in_force.items() if not law or a.law_id == law or a.law_name == law}
    by_row = {str(a.id): k for k, a in candidates.items()}

    rankings: dict[str, list[str]] = {}
    rankings["bm25"] = [by_row[i] for i, _ in _index(session).rank(q, list(by_row), options.depth)]
    if options.embedder is not None and candidates:
        rankings["vector"] = _vector_rank(q, list(candidates.values()), options.embedder,
                                          options.embed_model or "default", options.depth)
    fused = rrf(rankings, weights=WEIGHTS)
    via: dict[str, str] = {}
    if options.graph:
        fused, via = _graph_expand(fused, in_force, candidates, seeds=GRAPH_SEEDS,
                                   unmatched_per_seed=GRAPH_UNMATCHED_PER_SEED)
    positions = {name: {k: i for i, k in enumerate(r, 1)} for name, r in rankings.items()}
    results = []
    for key, score in fused[:limit]:
        a = candidates[key]
        channels = {name: pos[key] for name, pos in positions.items() if key in pos}
        if key in via:
            channels["graph"] = via[key]
        results.append({
            "id": str(a.id), "law_id": a.law_id, "law_name": a.law_name, "law_kind": a.law_kind,
            "article_key": a.article_key, "article_label": article_label(a.article_key), "title": a.title,
            "effective_from": a.effective_from.isoformat(),
            "effective_to": a.effective_to.isoformat() if a.effective_to else None,
            "source_url": a.source_url, "publisher": a.publisher, "content_hash": a.content_hash, "refs": a.refs,
            "score": round(score, 5), "channels": channels,
            "snippet": _snippet(a.text, q), "citation": f"{a.law_name} {article_label(a.article_key)}",
        })
    used = sorted(rankings) + (["graph"] if via else [])
    return {"query": q, "as_of": as_of.isoformat(), "mode": "hybrid", "channels": used,
            "total": len(fused), "results": results}


def embedder_from_env() -> tuple[Embedder | None, str | None]:
    """An EmbedHub embedder for ``SION_LAW_EMBED_MODEL`` (a registry key), or (None, None)."""
    import os

    key = os.getenv("SION_LAW_EMBED_MODEL")
    if not key:
        return None, None
    from sion_embedhub.providers import Embedder as HubEmbedder
    from sion_embedhub.registry import default_registry

    hub = HubEmbedder(default_registry().get(key))
    return (lambda texts, role: hub.embed(list(texts), role=role)), key
