"""Law-article ingestion + search (sion_api.law_knowledge)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sion_api.law_knowledge import content_hash, parse_article_key
from sion_api.main import create_app

DECREE_86 = {
    "law_id": "002118", "law_name": "건축법 시행령", "law_kind": "decree", "article_key": "제86조",
    "title": "일조 등의 확보를 위한 건축물의 높이 제한",
    "text": "전용주거지역이나 일반주거지역에서 건축물을 건축하는 경우에는 정북방향의 인접 대지경계선으로부터 "
            "높이 10미터 이하인 부분: 인접 대지경계선으로부터 1.5미터 이상, "
            "높이 10미터를 초과하는 부분: 인접 대지경계선으로부터 해당 건축물 각 부분 높이의 2분의 1 이상",
    "effective_from": "2024-01-01", "effective_to": "2026-11-11",
}
ACT_61_NEW = {
    "law_id": "001823", "law_name": "건축법", "article_key": "61",
    "title": "일조 등의 확보를 위한 건축물의 높이 제한",
    "text": "높이 10미터 이하인 부분은 1.5미터 이상, 높이 10미터 초과 17미터 이하인 부분은 5미터 이상 "
            "인접 대지경계선으로부터 띄어 건축하여야 한다.",
    "effective_from": "2026-11-12",
}
ACT_55 = {
    "law_id": "001823", "law_name": "건축법", "article_key": "55", "title": "건축물의 건폐율",
    "text": "대지면적에 대한 건축면적의 비율(이하 건폐율)의 최대한도는 국토의 계획 및 이용에 관한 법률 제77조에 따른다.",
    "effective_from": "2024-01-01", "refs": ["국토계획법:77"],
}


def _client() -> TestClient:
    return TestClient(create_app(database_url="sqlite://", auto_create_schema=True),
                      base_url="http://localhost", client=("127.0.0.1", 50000))


def _seed(c: TestClient) -> dict:
    r = c.post("/api/v1/law/articles", json={"articles": [DECREE_86, ACT_61_NEW, ACT_55]})
    assert r.status_code == 201, r.text
    return r.json()


def test_parse_article_key_forms():
    assert parse_article_key("제61조의2") == "61-2"
    assert parse_article_key("61조") == "61"
    assert parse_article_key("61-2") == "61-2"


def test_ingest_is_idempotent_and_versioned():
    with _client() as c:
        first = _seed(c)
        assert len(first["created"]) == 3 and first["unchanged"] == []
        again = c.post("/api/v1/law/articles", json={"articles": [ACT_55]}).json()
        assert again == {"created": [], "unchanged": ["001823:55@2024-01-01"]}


def test_changed_text_same_version_conflicts_and_rolls_back():
    with _client() as c:
        _seed(c)
        changed = {**ACT_55, "text": ACT_55["text"] + " 단서 추가"}
        new = {**ACT_55, "article_key": "56", "title": "건축물의 용적률"}
        r = c.post("/api/v1/law/articles", json={"articles": [new, changed]})
        assert r.status_code == 409
        assert c.get("/api/v1/law/articles/001823/56").status_code == 404  # whole batch rolled back


def test_rejects_bad_input():
    with _client() as c:
        bad_key = c.post("/api/v1/law/articles", json={"articles": [{**ACT_55, "article_key": "abc"}]})
        assert bad_key.status_code == 422
        bad_period = c.post("/api/v1/law/articles", json={"articles": [{**ACT_55, "effective_to": "2020-01-01"}]})
        assert bad_period.status_code == 422


def test_search_respects_as_of_date():
    with _client() as c:
        _seed(c)
        before = c.get("/api/v1/law/search", params={"q": "일조 높이 제한", "as_of": "2026-10-16"}).json()
        cites = [r["citation"] for r in before["results"]]
        assert "건축법 시행령 제86조" in cites and "건축법 제61조" not in cites
        after = c.get("/api/v1/law/search", params={"q": "일조 높이 제한", "as_of": "2026-11-12"}).json()
        cites = [r["citation"] for r in after["results"]]
        assert "건축법 제61조" in cites and "건축법 시행령 제86조" not in cites


def test_search_ranks_title_match_and_filters_law():
    with _client() as c:
        _seed(c)
        body = c.get("/api/v1/law/search", params={"q": "건폐율", "as_of": "2026-10-16"}).json()
        top = body["results"][0]
        assert top["citation"] == "건축법 제55조" and "건폐율" in top["snippet"]
        assert top["content_hash"] == content_hash(ACT_55["title"], ACT_55["text"])
        only_decree = c.get("/api/v1/law/search", params={"q": "높이", "law": "건축법 시행령", "as_of": "2026-10-16"}).json()
        assert {r["law_name"] for r in only_decree["results"]} == {"건축법 시행령"}


def test_search_requires_tokens_and_article_lookup():
    with _client() as c:
        _seed(c)
        assert c.get("/api/v1/law/search", params={"q": "!!"}).status_code == 422
        a = c.get("/api/v1/law/articles/001823/제61조", params={"as_of": "2026-12-01"}).json()
        assert a["article_label"] == "제61조" and a["effective_from"] == "2026-11-12"
        assert c.get("/api/v1/law/articles/001823/61", params={"as_of": "2026-10-01"}).status_code == 404
