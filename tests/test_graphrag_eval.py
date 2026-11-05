"""GraphRAG eval fixture regression (#81): 10 SketchUp queries stay answerable.

The fixture pins one query per modelling topic with its expected evidence
nodes. This test guards the contract, not retrieval quality:

* fixture loads and has exactly 10 unique query ids,
* every query carries >= 1 expected node and a non-empty question,
* expected nodes follow the ``sketchup:`` key scheme (no free text),
* cited knowledge docs (if present in repo) still exist.

Retrieval recall itself is measured live (needs the DB + embeddings), so it
is intentionally not asserted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "graphrag_eval.json"
KEY = re.compile(r"^sketchup:[a-z0-9-]+:[a-zA-Z0-9가-힣._:-]+$")
DOCS = [
    "docs/SKETCHUP_KNOWLEDGE.md",
    "docs/sketchup/MODELING-GUIDELINES.ko.md",
    "docs/sketchup/GROUPING-WORKFLOW.ko.md",
    "docs/GRAPHRAG.md",
]


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_eval_fixture_has_ten_unique_queries():
    data = _load()
    queries = data["queries"]
    assert len(queries) == 10
    assert len({q["id"] for q in queries}) == 10


def test_eval_queries_carry_evidence_keys():
    for q in _load()["queries"]:
        assert q["query"].strip(), q["id"]
        assert len(q["expected_nodes"]) >= 1, q["id"]
        for node in q["expected_nodes"]:
            assert KEY.match(node), f"{q['id']}: {node!r}"


def test_eval_acceptance_contract_present():
    acceptance = _load()["acceptance"]
    for key in ("mode", "top_k", "candidate_policy", "fact_source"):
        assert acceptance.get(key), key


def test_eval_cited_docs_exist():
    root = Path(__file__).resolve().parents[1]
    missing = [d for d in DOCS if not (root / d).is_file()]
    assert not missing, f"missing knowledge docs: {missing}"
