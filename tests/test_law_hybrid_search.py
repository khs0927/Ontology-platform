"""Hybrid law search (sion_api.law_search): bigram BM25, as_of, citation-graph lift, vectors, API modes."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.law_knowledge import LawArticleIn, ingest
from sion_api.law_search import HybridOptions, hybrid_search, tokens
from sion_api.main import create_app

ARTICLES = [
    {"law_id": "001823", "law_name": "건축법", "article_key": "55", "title": "건축물의 건폐율",
     "text": "대지면적에 대한 건축면적의 비율의 최대한도는 「국토의 계획 및 이용에 관한 법률」 제77조에 따른 건폐율의 기준에 따른다.",
     "effective_from": "2024-01-01"},
    {"law_id": "001200", "law_name": "국토의 계획 및 이용에 관한 법률", "article_key": "77", "title": "용도지역의 건폐율",
     "text": "용도지역에서 비율의 최대한도는 관할 구역의 면적과 인구 규모를 고려하여 다음 각 호의 범위에서 조례로 정한다.",
     "effective_from": "2024-01-01"},
    {"law_id": "001823", "law_name": "건축법", "article_key": "61", "title": "일조 등의 확보를 위한 건축물의 높이 제한",
     "text": "높이 10미터 이하인 부분은 인접 대지경계선으로부터 1.5미터 이상 띄어 건축하여야 한다.",
     "effective_from": "2026-11-12"},
    {"law_id": "002118", "law_name": "건축법 시행령", "law_kind": "decree", "article_key": "86",
     "title": "일조 등의 확보를 위한 건축물의 높이 제한",
     "text": "정북방향의 인접 대지경계선으로부터 높이 9미터 이하인 부분은 1.5미터 이상 띄어야 한다.",
     "effective_from": "2024-01-01", "effective_to": "2026-11-11"},
    {"law_id": "001823", "law_name": "건축법", "article_key": "44", "title": "대지와 도로의 관계",
     "text": "건축물의 대지는 2미터 이상이 도로에 접하여야 한다.", "effective_from": "2024-01-01"},
]


@pytest.fixture
def session():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with build_session_factory(engine)() as s:
        ingest(s, [LawArticleIn(**a) for a in ARTICLES])
        yield s


def keys(result):
    return [f"{r['law_name']}:{r['article_key']}" for r in result["results"]]


def test_bigrams_match_inflected_korean(session):
    assert {"건폐", "폐율"} <= set(tokens("건폐율은"))
    result = hybrid_search(session, "건폐율은 어떻게 정하나요", as_of=date(2026, 11, 12), options=HybridOptions(graph=False))
    assert keys(result)[0] == "건축법:55" and result["mode"] == "hybrid" and result["channels"] == ["bm25"]


def test_citation_graph_lifts_the_cited_article_below_its_citer(session):
    plain = keys(hybrid_search(session, "건축물 건폐율 기준", as_of=date(2026, 11, 12), options=HybridOptions(graph=False)))
    lifted = hybrid_search(session, "건축물 건폐율 기준", as_of=date(2026, 11, 12))
    order = keys(lifted)
    assert order[0] == "건축법:55" and order[1] == "국토의 계획 및 이용에 관한 법률:77"
    assert plain.index("국토의 계획 및 이용에 관한 법률:77") >= 1
    second = lifted["results"][1]
    assert second["channels"]["graph"] == "건축법:55" and "graph" in lifted["channels"]


def test_as_of_selects_the_version_in_force(session):
    before = keys(hybrid_search(session, "일조 높이 제한", as_of=date(2026, 11, 11)))
    after = keys(hybrid_search(session, "일조 높이 제한", as_of=date(2026, 11, 12)))
    assert "건축법 시행령:86" in before and "건축법:61" not in before
    assert "건축법:61" in after and "건축법 시행령:86" not in after


def test_law_filter(session):
    result = hybrid_search(session, "건폐율", law="001200", as_of=date(2026, 11, 12))
    assert keys(result) == ["국토의 계획 및 이용에 관한 법률:77"]


def test_vector_channel_is_fused_by_rank(session):
    calls = []

    def fake_embedder(texts, role):
        calls.append((role, len(texts)))
        # "도로" articles point one way, everything else the other
        return [[1.0, 0.0] if "도로" in t else [0.0, 1.0] for t in texts]

    options = HybridOptions(embedder=fake_embedder, embed_model="fake", graph=False)
    result = hybrid_search(session, "도로", as_of=date(2026, 11, 12), options=options)
    assert result["channels"] == ["bm25", "vector"]
    top = result["results"][0]
    assert keys(result)[0] == "건축법:44" and top["channels"] == {"bm25": 1, "vector": 1}
    assert calls[0][0] == "passage" and calls[-1] == ("query", 1)
    hybrid_search(session, "도로", as_of=date(2026, 11, 12), options=options)
    assert [c for c in calls if c[0] == "passage"] == [calls[0]]  # article vectors are cached by content hash


def test_api_defaults_to_hybrid_and_keeps_lexical_mode():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        assert c.post("/api/v1/law/articles", json={"articles": ARTICLES}).status_code == 201
        hybrid = c.get("/api/v1/law/search", params={"q": "건폐율은", "as_of": "2026-11-12"}).json()
        assert hybrid["mode"] == "hybrid" and hybrid["results"][0]["citation"] == "건축법 제55조"
        lexical = c.get("/api/v1/law/search", params={"q": "건폐율", "mode": "lexical", "as_of": "2026-11-12"}).json()
        assert lexical["mode"] == "lexical"
        assert c.get("/api/v1/law/search", params={"q": "!!!"}).status_code == 422
