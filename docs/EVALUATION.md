# Retrieval evaluation

Every retrieval change is judged on one gold set before it is merged: the Korean building-law
questions in `data/eval/building-law-gold.v1.jsonl` over the statute corpus in
`data/eval/law-corpus.v1.jsonl.gz` (see `data/eval/PROVENANCE.md`). The harness is
`sion_eval` (`packages/eval`).

```bash
uv run python -m sion_eval.cli run                       # all retrievers, k=10
uv run python -m sion_eval.cli run --retriever bm25-bigram --out report.json
```

The JSON report has overall and per-category means plus every query's ranked keys, so a
regression can be traced to individual questions.

## Metrics

- `hit@1`, `hit@5`: share of questions with at least one relevant article in the top 1 / 5.
- `recall@5`, `recall@10`: share of a question's relevant articles found in the top 5 / 10, averaged.
- `mrr`: mean reciprocal rank of the first relevant article.
- `ndcg@10`: rank-weighted recall.

## Baseline (2026-11-12, 1,159 articles, 44 questions)

| Retriever | hit@1 | hit@5 | recall@5 | recall@10 | mrr | ndcg@10 |
| --- | --- | --- | --- | --- | --- | --- |
| `law-search` (current `/api/v1/law/search`) | 0.250 | 0.636 | 0.625 | 0.625 | 0.422 | 0.471 |
| `bm25-word` | 0.364 | 0.636 | 0.591 | 0.716 | 0.496 | 0.531 |
| `bm25-bigram` | 0.636 | 0.955 | 0.920 | 0.977 | 0.768 | 0.806 |

Recall@10 and MRR by category:

| Retriever | single (27) | cross (10) | numeric (7) |
| --- | --- | --- | --- |
| `law-search` | 0.556 / 0.349 | 0.550 / 0.433 | 1.000 / 0.691 |
| `bm25-word` | 0.741 / 0.491 | 0.800 / 0.681 | 0.500 / 0.250 |
| `bm25-bigram` | 1.000 / 0.710 | 0.900 / 0.839 | 1.000 / 0.893 |

What the numbers say:

- The production law search misses 37.5% of relevant articles in its top 10. It matches whole
  words, so `건폐율은` does not match `건폐율`, and it has no IDF weighting.
- Character bigrams alone lift recall@10 from 0.63 to 0.98. Korean-aware tokenization is the
  first fix for hybrid search (upgrade phase 4).
- The weak spot left is ranking (hit@1 0.64) and cross-article questions, where the decree that
  holds the number is ranked below the act that delegates it. Graph expansion over
  `refs` (act -> decree) and reranking are the next levers.
- The questions reuse much of the statutes' own wording, so lexical methods are favoured here.
  Add paraphrased and drawing-based questions before trusting small differences between
  vector retrievers.

`tests/test_eval_building_law.py` holds floors slightly under these numbers; a retriever change
that drops below them fails CI. Raise the floors when a change improves the numbers.

## Phase 4: hybrid search (2026-11-12)

`GET /api/v1/law/search` now defaults to `mode=hybrid` (`sion_api.law_search`). The old scorer
is still available as `mode=lexical`. The hybrid search combines these channels:
- bigram BM25;
- an optional vector channel (`SION_LAW_EMBED_MODEL`), fused with BM25 by RRF;
- citation-graph expansion over `law_articles.refs` (upgrade phase 3).

| Retriever | hit@1 | hit@5 | recall@5 | recall@10 | mrr | ndcg@10 |
| --- | --- | --- | --- | --- | --- | --- |
| `law-search` (`mode=lexical`) | 0.250 | 0.636 | 0.625 | 0.625 | 0.422 | 0.471 |
| `law-hybrid-nograph` | 0.636 | 0.955 | 0.920 | 0.977 | 0.768 | 0.806 |
| `law-hybrid` (default) | 0.636 | 0.909 | 0.898 | 0.977 | 0.770 | 0.815 |

What the numbers say:

- The production endpoint goes from recall@10 0.625 to 0.977 and from MRR 0.422 to 0.770.
- **Graph expansion is close to neutral on this gold set.** nDCG and MRR rise slightly, and
  recall@5 drops on one question. Most cross questions already find both articles lexically,
  because the gold questions repeat the statutes' wording.
- Adding graph expansion as a third RRF list was tried first and failed: recall@10 fell to 0.614
  and hit@1 to 0.045. RRF adds the scores, so cited articles overtook the articles that cite
  them. The shipped version instead lifts cited articles to sit just below their citer. It does
  this only for articles that the other channels also matched, from the top 3 hits.
- Expanding to cited articles that no other channel matched (one per hit) lowered every metric,
  so it is off.
- Vectors are not scored here: no embedding endpoint was available. Measure them with
  `--retriever` once `SION_LAW_EMBED_MODEL` is set, and add paraphrased questions first (see
  above).
