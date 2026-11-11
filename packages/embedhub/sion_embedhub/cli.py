"""python -m sion_embedhub.cli {models|probe|bench|bench-drawings} ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bench import load_dataset, run
from .keys import KeyPool
from .providers import Embedder, EmbedError
from .registry import default_registry


def _lazy_key_pool():
    """Build the NVIDIA key pool on first use.

    Discovery alone must never fail: listing the registry or benchmarking a local model (bge-m3)
    needs no NVIDIA key, so the pool is only created when an NVIDIA model is actually invoked.
    """
    pool = None

    def get():
        nonlocal pool
        if pool is None:
            pool = KeyPool.from_env("NVIDIA_API_KEY")
        return pool

    return get


def _embedder(spec, get_pool):
    return Embedder(spec, get_pool() if spec.provider == "nvidia" else None)


def _model_key(token: str) -> str:
    return token.split(":", 1)[0].split("@", 1)[0]


def _optional_pool() -> KeyPool | None:
    """The pool when at least one NVIDIA key is configured, else None.

    ``KeyPool.from_env`` deliberately returns an empty pool instead of raising, so "no key" is
    ``len(pool) == 0`` here; the benchmark uses None to mean "not a live run".
    """
    pool = KeyPool.from_env("NVIDIA_API_KEY")
    return pool if len(pool) else None


def _cmd_bench_drawings(a, reg) -> int:
    """Render the existing Korean corpus and score it. Live NVIDIA is opt-in."""
    from .drawings import DEFAULT_MODELS, FakeEmbedder, build_drawing_corpus, score_drawings

    tokens = list(a.models) if a.models else list(DEFAULT_MODELS)
    needs_nvidia = any(reg.get(_model_key(token)).provider == "nvidia" for token in tokens)
    pool = _optional_pool() if (not a.offline and needs_nvidia) else None
    live = not a.offline and (pool is not None or not needs_nvidia)
    if a.results and not live:
        print("refusing to write results: not a live model run", file=sys.stderr)
        return 2

    dataset = build_drawing_corpus(a.out_dir)
    if not live:
        if not a.offline:
            print(json.dumps({
                "live": False,
                "skipped": True,
                "reason": "NVIDIA_API_KEY not set",
                "rendered": True,
            }, ensure_ascii=False, indent=2))
            return 0
        embedders, dims = {}, {}
        for token in tokens:
            name = f"offline:{token}"
            embedders[name] = FakeEmbedder()
            _key, sep, dim = token.partition(":")
            if sep:
                dims[name] = int(dim)
        report = score_drawings(dataset, embedders, dims)
        report["live"] = False
        report["provider"] = "fake"
        report["note"] = "Offline fake embedder. Not an NVIDIA result."
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    dims, embedders = {}, {}
    for token in tokens:
        spec = reg.get(_model_key(token))
        # ``pool`` is a concrete pool here (a live run), so bypass the lazy factory used by `bench`.
        embedders[token] = Embedder(spec, pool if spec.provider == "nvidia" else None)
        _key, sep, dim = token.partition(":")
        if sep:
            dims[token] = int(dim)
    try:
        report = score_drawings(dataset, embedders, dims)
    except EmbedError as ex:
        print(f"benchmark aborted: {ex}", file=sys.stderr)
        return 2
    report["live"] = True
    report["provider"] = "nvidia" if needs_nvidia else "local"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.results:
        Path(a.results).write_text(text + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sion-embedhub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models", help="list registry and discovered key count (names only)")
    p = sub.add_parser("probe", help="live-check each model: dimension, query/passage, image")
    p.add_argument("--models", nargs="*")
    b = sub.add_parser("bench", help="recall@k / MRR per model + RRF fusion")
    b.add_argument("dataset")
    b.add_argument("--models", nargs="+", required=True, help="registry keys, optionally key:dim (e.g. nv-1b:1024)")
    d = sub.add_parser("bench-drawings", help="render the Korean drawing corpus and score recall@k / MRR")
    d.add_argument("out_dir", help="directory for renders/ and drawings.jsonl (not committed)")
    d.add_argument("--models", nargs="+", default=None,
                   help="default: nv-1b:1024 nv-vl:1024 nv-vl@image:1024")
    d.add_argument("--offline", action="store_true",
                   help="score with a fake embedder; no NVIDIA call (what CI runs)")
    d.add_argument("--results", help="write the JSON report; refused unless this run called the models")
    a = ap.parse_args(argv)

    reg = default_registry()

    if a.cmd == "bench-drawings":
        return _cmd_bench_drawings(a, reg)

    if a.cmd == "models":
        # env discovery only - an empty list is a valid answer and must not error
        keys = KeyPool.from_env("NVIDIA_API_KEY").names
        print(json.dumps({"nvidia_keys": keys,
                          "models": {k: {"model": s.model, "dims": s.dims, "modalities": s.modalities} for k, s in reg.specs.items()}},
                         ensure_ascii=False, indent=2))
        return 0

    get_pool = _lazy_key_pool()

    if a.cmd == "probe":
        rc = 0
        for key in (a.models or list(reg.specs)):
            spec = reg.get(key)
            try:
                e = _embedder(spec, get_pool)
                dim = len(e.embed(["외벽 단열재 두께 A-101"], "query")[0])
                res = {"ok": True, "dim": dim}
            except Exception as ex:  # report, keep probing the rest
                res, rc = {"ok": False, "err": str(ex)[:160]}, 1
            print(key, json.dumps(res, ensure_ascii=False))
        return rc

    dims, embedders = {}, {}
    for token in a.models:
        key, _, d = token.partition(":")
        spec = reg.get(key.split("@", 1)[0])  # "nv-vl@image" = same model, index the image side
        embedders[token] = _embedder(spec, get_pool)
        if d:
            dims[token] = int(d)
    docs, queries = load_dataset(a.dataset)
    try:
        print(json.dumps(run(embedders, docs, queries, dims, Path(a.dataset).parent), ensure_ascii=False, indent=2))
    except EmbedError as ex:
        print(f"benchmark aborted: {ex}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
