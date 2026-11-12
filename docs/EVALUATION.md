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
