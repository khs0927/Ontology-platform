# Evaluation data provenance

## `law-corpus.v1.jsonl.gz`

- 1,159 statute articles from 15 Korean laws, decrees and rules (건축법, 건축법 시행령·시행규칙,
  국토의 계획 및 이용에 관한 법률 and its 시행령, 주차장법, 도시개발법, …).
- Source: `packages/law-ingest/data/processed/articles.jsonl` in khs0927/korean-building-law-monorepo
  at commit `a5fec7e115a36249bb1cd6709fa34f5343f8a123` (2026-10-13), originally from 국가법령정보센터.
- Transformation: the article key is parsed from each article's own heading (`제4조의2` -> `4-2`),
  because the source `article_no` field drops the `의N` branch; deleted articles (`… 삭제 <date>`)
  are dropped. One line per article: `law_name`, `article_key`, `title`, `text`.
- Statutes are not protected works under 저작권법 제7조 (법령), so the text can be redistributed.
- **Not a legal source of truth.** The snapshot has no effective dates and is not kept current; use
  it only to compare retrievers. Legal answers must come from `law_articles` with effective dates.

## `building-law-gold.v1.jsonl`

44 questions written for this repository on 2026-11-12. Each lists the corpus keys a correct
retrieval must return. Every relevant article was read before it was listed.

| Category | Count | Meaning |
| --- | --- | --- |
| `single` | 27 | one article answers it |
| `cross` | 10 | the answer spans articles, usually an act and its decree |
| `numeric` | 7 | the answer is a number or range in a table-like list |

`as_of` (amendment and effective-date) questions are reserved for when the corpus carries
effective dates.
