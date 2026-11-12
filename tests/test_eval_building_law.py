"""Building-law retrieval evaluation (sion_eval): gold set integrity, metrics, baseline floors."""

from __future__ import annotations

import pytest
from sion_eval import load_goldset, load_law_corpus, validate_goldset
from sion_eval.metrics import evaluate, hit_at, ndcg_at, recall_at, reciprocal_rank, summarize
from sion_eval.retrievers import RETRIEVERS, bigram_tokens


@pytest.fixture(scope="module")
def corpus():
    return load_law_corpus()


@pytest.fixture(scope="module")
def gold():
    return load_goldset()


def test_corpus_keys_are_unique_and_parsed(corpus):
    assert len(corpus) > 1000
    keys = {d.key for d in corpus}
    assert len(keys) == len(corpus)
    assert "건축법:61" in keys and "건축법 시행령:27-2" in keys
    assert all(d.text.startswith("제") for d in corpus)


def test_goldset_is_answerable_from_the_corpus(gold, corpus):
    assert len(gold) >= 40
    assert validate_goldset(gold, corpus) == []
    assert {q.category for q in gold} >= {"single", "cross", "numeric"}


def test_validate_goldset_reports_missing_keys(gold, corpus):
    from sion_eval.goldset import GoldQuery

    bad = [*gold[:1], GoldQuery("x", "q", "single", ("건축법:9999",)), GoldQuery("x", "", "weird", ())]
    problems = validate_goldset(bad, corpus)
    assert any("not in corpus" in p for p in problems)
    assert any("duplicate" in p for p in problems)
    assert any("unknown category" in p for p in problems)
    assert any("empty query" in p for p in problems)


def test_metrics():
    ranked = ["a", "x", "b", "y"]
    assert recall_at(ranked, {"a", "b"}, 2) == 0.5 and recall_at(ranked, {"a", "b"}, 3) == 1.0
    assert hit_at(ranked, {"b"}, 1) == 0.0 and hit_at(ranked, {"b"}, 3) == 1.0
    assert reciprocal_rank(ranked, {"b"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(ranked, {"z"}) == 0.0
    assert ndcg_at(["a", "b"], {"a", "b"}, 10) == pytest.approx(1.0)
    assert 0 < ndcg_at(["x", "a"], {"a"}, 10) < 1


def test_summarize_groups_by_category(gold):
    rows = evaluate(gold[:3], lambda q, k: [], k=10)
    s = summarize(rows)
    assert s["overall"]["n"] == 3 and s["overall"]["recall@10"] == 0.0
    assert sum(c["n"] for c in s["by_category"].values()) == 3


def test_bigram_tokens_split_inflected_korean():
    assert {"건폐", "폐율"} <= set(bigram_tokens("건폐율은"))


# Floors sit a little under the numbers recorded in docs/EVALUATION.md; a drop below them is a regression.
@pytest.mark.parametrize(("name", "recall_floor", "mrr_floor"), [
    ("bm25-bigram", 0.95, 0.72),
    ("bm25-word", 0.68, 0.45),
    ("law-search", 0.60, 0.40),
])
def test_baseline_floors(name, recall_floor, mrr_floor, gold, corpus):
    rows = evaluate(gold, RETRIEVERS[name](corpus), k=10)
    overall = summarize(rows)["overall"]
    assert overall["recall@10"] >= recall_floor, overall
    assert overall["mrr"] >= mrr_floor, overall
