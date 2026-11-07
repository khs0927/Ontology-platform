"""Retrieval benchmark: same corpus + labelled queries through several embedding spaces.

Dataset (JSONL, one object per line):
  {"type":"doc","id":"d1","text":"..."}                    # text document
  {"type":"doc","id":"d2","image":"path/to/render.png"}     # image document (needs a multimodal model)
  {"type":"query","q":"외벽 단열재 두께","relevant":["d1"]}
Docs may carry both "text" and "image"; the model indexes whichever it supports.
Reports recall@k and MRR per model plus the RRF fusion of all models.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .fusion import agreement, rrf
from .providers import Embedder, image_to_data_url


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def load_dataset(path: str | Path) -> tuple[list[dict], list[dict]]:
    docs, qs = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            (docs if o["type"] == "doc" else qs).append(o)
    return docs, qs


def rank_for_model(emb: Embedder, docs: list[dict], queries: list[dict], dim: int | None = None, base_dir: Path | None = None,
                   prefer: str = "text") -> list[list[str]]:
    """One ranked doc-id list per query, in this model's own space.

    ``prefer`` picks which side of a doc carrying both text and image gets indexed
    ("text" or "image"); a doc lacking the preferred side falls back to the other one.
    """
    mods = emb.spec.modalities
    order_ = ("image", "text") if prefer == "image" else ("text", "image")
    ids, payload = [], []
    for d in docs:
        for side in order_:
            if side in d and side in mods:
                ids.append(d["id"])
                payload.append(d["text"] if side == "text" else image_to_data_url((base_dir or Path()) / d["image"]))
                break
    if not ids:
        return [[] for _ in queries]
    dv = emb.embed(payload, "passage", dim)
    qv = emb.embed([q["q"] for q in queries], "query", dim)
    ranked = []
    for v in qv:
        order = sorted(range(len(ids)), key=lambda i: -_dot(v, dv[i]))
        ranked.append([ids[i] for i in order])
    return ranked


def metrics(ranked: list[list[str]], queries: list[dict], ks: Sequence[int] = (1, 5, 10)) -> dict:
    n = len(queries)
    out = {f"recall@{k}": 0.0 for k in ks}
    out["mrr"] = 0.0
    for r, q in zip(ranked, queries, strict=True):
        rel = set(q["relevant"])
        for k in ks:
            out[f"recall@{k}"] += bool(rel & set(r[:k]))
        out["mrr"] += next((1.0 / (i + 1) for i, x in enumerate(r) if x in rel), 0.0)
    return {k: round(v / n, 4) for k, v in out.items()} if n else out


def run(embedders: Mapping[str, Embedder], docs: list[dict], queries: list[dict], dims: Mapping[str, int] | None = None, base_dir: Path | None = None) -> dict:
    # a run name like "nv-vl@image:1024" indexes the image side of each doc (see cli); plain names index text
    per_model = {name: rank_for_model(e, docs, queries, (dims or {}).get(name), base_dir,
                                      "image" if "@image" in name else "text")
                 for name, e in embedders.items()}
    report = {"models": {name: metrics(r, queries) for name, r in per_model.items()}}
    fused = []
    verdicts: dict[str, int] = {}
    for qi in range(len(queries)):
        rankings = {name: r[qi] for name, r in per_model.items() if r[qi]}
        fused.append([i for i, _ in rrf(rankings)])
        v = agreement(rankings, top=5)["verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1
    report["rrf_fusion"] = metrics(fused, queries)
    report["agreement"] = verdicts
    return report
