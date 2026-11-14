"""Retrieval evaluation for Sion: gold sets, metrics and baseline retrievers.

Every retrieval change (parsers, extraction, hybrid search, rerankers) is judged by the
numbers this package produces on the Korean building-law gold set
(``data/eval/building-law-gold.v1.jsonl``) over the statute corpus
(``data/eval/law-corpus.v1.jsonl.gz``). See docs/EVALUATION.md.
"""

from .corpus import Doc, load_law_corpus
from .goldset import GoldQuery, load_goldset, validate_goldset
from .metrics import evaluate, summarize

__all__ = [
    "Doc",
    "GoldQuery",
    "evaluate",
    "load_goldset",
    "load_law_corpus",
    "summarize",
    "validate_goldset",
]
