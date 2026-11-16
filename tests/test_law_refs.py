"""Law cross-references (sion_api.law_refs) and the /refs endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sion_api.law_refs import extract_refs, family_root, ref_keys
from sion_api.main import create_app

KNOWN = ["국토의 계획 및 이용에 관한 법률"]


def test_family_words_and_heading():
    text = "제115조의3(이행강제금의 탄력적 운영) ① 법 제80조제1항제1호에서 정한다. 영 제3조, 규칙 제2조"
    refs = extract_refs(text, "건축법 시행령", self_key="115-3")
    assert [r.key for r in refs] == ["건축법:80", "건축법 시행령:3", "건축법 시행규칙:2"]
    assert refs[0].detail == "제1항제1호"
    assert family_root("건축법 시행규칙") == "건축법"


def test_bracketed_same_law_lists_ranges_and_appendix():
    text = ("「주택법」 제15조 및 같은 법 제16조에 따른다. 제5조부터 제8조까지의 규정, "
            "이 영 제11조, 제14조 및 제16조의2. [별표 3의2]")
    assert ref_keys(text, "건축법 시행령") == [
        "주택법:15", "주택법:16",
        "건축법 시행령:5", "건축법 시행령:6", "건축법 시행령:7", "건축법 시행령:8",
        "건축법 시행령:11", "건축법 시행령:14", "건축법 시행령:16-2", "건축법 시행령:별표3-2",
    ]


def test_unbracketed_names_and_self_reference():
    text = "국토의 계획 및 이용에 관한 법률 제77조에 따른다. 주차장법 제19조. 이 법 제61조, 제11조"
    assert ref_keys(text, "건축법", self_key="61", known_laws=KNOWN) == [
        "국토의 계획 및 이용에 관한 법률:77", "주차장법:19", "건축법:11"]
    # without the list, a multi-word unbracketed name falls back to the article's own law
    assert ref_keys("관한 법률 제77조", "건축법")[0] == "건축법:77"


def test_ranges_are_capped_and_branch_articles_not_expanded():
    assert ref_keys("제1조부터 제90조까지", "건축법") == ["건축법:1", "건축법:90"]
    assert ref_keys("제5조의2부터 제6조까지", "건축법") == ["건축법:5-2", "건축법:6"]


ACT_55 = {"law_id": "001823", "law_name": "건축법", "article_key": "55", "title": "건축물의 건폐율",
          "text": "건폐율의 최대한도는 「국토의 계획 및 이용에 관한 법률」 제77조에 따른 건폐율의 기준에 따른다. "
                  "다만, 이 법 제56조에서 달리 정한 경우에는 그러하지 아니하다.",
          "effective_from": "2024-01-01"}
ACT_56 = {"law_id": "001823", "law_name": "건축법", "article_key": "56", "title": "건축물의 용적률",
          "text": "용적률의 최대한도는 「국토의 계획 및 이용에 관한 법률」 제78조에 따른다.", "effective_from": "2024-01-01"}
KUKTO_77 = {"law_id": "001200", "law_name": "국토의 계획 및 이용에 관한 법률", "article_key": "77",
            "title": "용도지역의 건폐율", "text": "용도지역에서 건폐율의 최대한도는 다음 각 호의 범위에서 정한다.",
            "effective_from": "2024-01-01"}
MANUAL = {"law_id": "001823", "law_name": "건축법", "article_key": "57", "title": "대지의 분할 제한",
          "text": "제55조와 제56조에 따른 기준에 못 미치게 분할할 수 없다.", "effective_from": "2024-01-01",
          "refs": ["건축법:55"]}


def _client() -> TestClient:
    return TestClient(create_app(database_url="sqlite://", auto_create_schema=True),
                      base_url="http://localhost", client=("127.0.0.1", 50000))


def test_ingest_fills_refs_and_endpoint_resolves_both_directions():
    with _client() as c:
        assert c.post("/api/v1/law/articles", json={"articles": [ACT_55, ACT_56, KUKTO_77, MANUAL]}).status_code == 201
        body = c.get("/api/v1/law/articles/001823/제55조/refs", params={"as_of": "2026-11-12"}).json()
        assert body["article"]["citation"] == "건축법 제55조"
        assert [(o["ref"], o["resolved"]) for o in body["outgoing"]] == [
            ("국토의 계획 및 이용에 관한 법률:77", True), ("건축법:56", True)]
        assert body["outgoing"][0]["law_id"] == "001200" and body["outgoing"][0]["content_hash"].startswith("sha256:")
        assert [i["citation"] for i in body["incoming"]] == ["건축법 제57조"]  # manual refs are kept as given

        out56 = c.get("/api/v1/law/articles/001823/56/refs").json()["outgoing"]
        assert out56 == [{"ref": "국토의 계획 및 이용에 관한 법률:78", "resolved": False}]  # listed, not dropped
        assert c.get("/api/v1/law/articles/001823/99/refs").status_code == 404
        assert c.get("/api/v1/law/articles/001823/x/refs").status_code == 422

        rebuilt = c.post("/api/v1/law/refs/rebuild", params={"only_empty": False}).json()
        assert rebuilt == {"updated": 1, "only_empty": False}  # the manual row gains 제56조
        incoming56 = c.get("/api/v1/law/articles/001823/56/refs").json()["incoming"]
        assert [i["citation"] for i in incoming56] == ["건축법 제55조", "건축법 제57조"]
