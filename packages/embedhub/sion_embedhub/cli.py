"""python -m sion_embedhub.cli {models|probe|bench} ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bench import load_dataset, run
from .keys import KeyPool
from .providers import Embedder, EmbedError
from .registry import default_registry


def _embedder(spec, pool):
    return Embedder(spec, pool if spec.provider == "nvidia" else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sion-embedhub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models", help="list registry and discovered key count (names only)")
    p = sub.add_parser("probe", help="live-check each model: dimension, query/passage, image")
    p.add_argument("--models", nargs="*")
    b = sub.add_parser("bench", help="recall@k / MRR per model + RRF fusion")
    b.add_argument("dataset")
    b.add_argument("--models", nargs="+", required=True, help="registry keys, optionally key:dim (e.g. nv-1b:1024)")
    a = ap.parse_args(argv)

    reg = default_registry()
    pool = KeyPool.from_env("NVIDIA_API_KEY") if any(s.provider == "nvidia" for s in reg.specs.values()) else None

    if a.cmd == "models":
        print(json.dumps({"nvidia_keys": (pool.names if pool else []),
                          "models": {k: {"model": s.model, "dims": s.dims, "modalities": s.modalities} for k, s in reg.specs.items()}},
                         ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "probe":
        rc = 0
        for key in (a.models or list(reg.specs)):
            spec = reg.get(key)
            try:
                e = _embedder(spec, pool)
                dim = len(e.embed(["외벽 단열재 두께 A-101"], "query")[0])
                res = {"ok": True, "dim": dim}
            except Exception as ex:  # report, keep probing the rest
                res, rc = {"ok": False, "err": str(ex)[:160]}, 1
            print(key, json.dumps(res, ensure_ascii=False))
        return rc

    dims, embedders = {}, {}
    for token in a.models:
        key, _, d = token.partition(":")
        spec = reg.get(key)
        embedders[token] = _embedder(spec, pool)
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
