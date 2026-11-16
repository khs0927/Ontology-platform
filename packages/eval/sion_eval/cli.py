"""``python -m sion_eval.cli run`` scores retrievers on the gold set and writes a JSON report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .corpus import DEFAULT_CORPUS, load_law_corpus
from .goldset import DEFAULT_GOLDSET, load_goldset, validate_goldset
from .metrics import evaluate, summarize
from .retrievers import RETRIEVERS


def run(retrievers: list[str], *, k: int = 10, corpus: Path = DEFAULT_CORPUS, goldset: Path = DEFAULT_GOLDSET) -> dict:
    docs = load_law_corpus(corpus)
    gold = load_goldset(goldset)
    problems = validate_goldset(gold, docs)
    if problems:
        raise SystemExit("gold set invalid:\n" + "\n".join(problems))
    report: dict = {"corpus": str(Path(corpus).name), "goldset": str(Path(goldset).name), "documents": len(docs),
                    "queries": len(gold), "k": k, "runs": {}}
    for name in retrievers:
        started = time.perf_counter()
        retrieve = RETRIEVERS[name](docs)
        rows = evaluate(gold, retrieve, k=k)
        report["runs"][name] = {"seconds": round(time.perf_counter() - started, 2), **summarize(rows), "queries": rows}
    return report


def _table(report: dict) -> str:
    k = report["k"]
    cols = ["hit@1", "hit@5", "recall@5", f"recall@{k}", "mrr", f"ndcg@{k}"]
    lines = ["| retriever | " + " | ".join(cols) + " |", "| --- |" + " --- |" * len(cols)]
    for name, run_ in report["runs"].items():
        o = run_["overall"]
        lines.append(f"| {name} | " + " | ".join(f"{o[c]:.3f}" for c in cols) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sion_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score retrievers on the gold set")
    r.add_argument("--retriever", action="append", choices=sorted(RETRIEVERS), help="repeatable; default: all")
    r.add_argument("--k", type=int, default=10)
    r.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    r.add_argument("--goldset", type=Path, default=DEFAULT_GOLDSET)
    r.add_argument("--out", type=Path, help="write the full JSON report here")
    args = p.parse_args(argv)
    report = run(args.retriever or sorted(RETRIEVERS), k=args.k, corpus=args.corpus, goldset=args.goldset)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(_table(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
