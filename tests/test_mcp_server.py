"""Remote MCP server (sion_api.mcp_server): tools, stateless Streamable HTTP transport, auth."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp")

from sion_api import models  # noqa: E402
from sion_api.auth import AuthPolicy  # noqa: E402
from sion_api.db import Base, build_engine, build_session_factory  # noqa: E402
from sion_api.law_knowledge import LawArticleIn, ingest  # noqa: E402
from sion_api.mcp_server import KnowledgeTools, build_app  # noqa: E402
from sion_api.repository import seed_core_types  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

READ = "read-token-123456789012"
PROJECT = "proj-token-1234567890123"
WRITE_ONLY = "write-token-12345678901"
ARTICLES = [
    {"law_id": "001823", "law_name": "건축법", "article_key": "55", "title": "건축물의 건폐율",
     "text": "건폐율의 최대한도는 「국토의 계획 및 이용에 관한 법률」 제77조에 따른다.", "effective_from": "2024-01-01"},
    {"law_id": "001200", "law_name": "국토의 계획 및 이용에 관한 법률", "article_key": "77", "title": "용도지역의 건폐율",
     "text": "용도지역에서 건폐율의 최대한도는 다음 범위에서 조례로 정한다.", "effective_from": "2024-01-01"},
]


@pytest.fixture
def factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    f = build_session_factory(engine)
    with f() as s:
        seed_core_types(s)
        ingest(s, [LawArticleIn(**a) for a in ARTICLES])
        a = models.Entity(stable_key="tool:lightrag", name="LightRAG", entity_type_id="Tool", description="graph RAG engine")
        b = models.Entity(stable_key="tool:pg", name="PostgreSQL", entity_type_id="Tool")
        c = models.Entity(stable_key="tool:neo4j", name="Neo4j", entity_type_id="Tool")
        s.add_all([a, b, c])
        s.flush()
        fact = models.Relation(stable_key="r1", source_entity_id=a.id, target_entity_id=b.id, relation_type_id="USES",
                               verification_state="human_verified", confidence=0.9, properties={})
        cand = models.Relation(stable_key="cand:r2", source_entity_id=a.id, target_entity_id=c.id,
                               relation_type_id="USES", verification_state="unverified", confidence=0.4,
                               properties={"candidate": True})
        s.add_all([fact, cand])
        s.flush()
        s.add(models.Evidence(relation_id=fact.id, source_uri="file:///docs/stack.md", source_locator="line:3",
                              verification_state="human_verified", extractor="manual",
                              properties={"excerpt": "LightRAG uses PostgreSQL"}))
        s.commit()
    return f


# --------------------------------------------------------------------------- tool bodies


def test_search_and_fetch_follow_the_connector_contract(factory):
    tools = KnowledgeTools(factory)
    hits = tools.search("건폐율")["results"]
    assert hits[0] == {"id": "law:001823:55", "title": "건축법 제55조 건축물의 건폐율",
                       "url": "/api/v1/law/articles/001823/55"}
    doc = tools.fetch("law:001823:55")
    assert set(doc) == {"id", "title", "text", "url", "metadata"} and "제77조" in doc["text"]
    assert doc["metadata"]["refs"] == ["국토의 계획 및 이용에 관한 법률:77"]
    assert tools.search("LightRAG")["results"][-1]["id"] == "entity:tool:lightrag"
    entity = tools.fetch("entity:tool:lightrag")
    assert "out USES PostgreSQL" in entity["text"] and "Neo4j" not in entity["text"]  # candidate hidden
    with pytest.raises(ValueError):
        tools.fetch("other:1")


def test_law_and_graph_tools(factory):
    tools = KnowledgeTools(factory)
    assert tools.law_article("001823", "제55조", "2026-11-12")["article_label"] == "제55조"
    refs = tools.law_refs("001823", "55")
    assert refs["outgoing"][0]["resolved"] is True and refs["outgoing"][0]["law_id"] == "001200"
    assert tools.law_search("건폐율", law="001200")["results"][0]["article_key"] == "77"
    with pytest.raises(ValueError, match="in force"):
        tools.law_article("001823", "55", "2020-01-01")

    hood = tools.neighbors("LightRAG")["neighbors"]
    assert [(n["relation"], n["entity"]["name"], n["candidate"]) for n in hood] == [("USES", "PostgreSQL", False)]
    with_candidates = tools.neighbors("tool:lightrag", include_candidates=True)["neighbors"]
    assert {n["entity"]["name"]: n["candidate"] for n in with_candidates} == {"PostgreSQL": False, "Neo4j": True}
    evidence = tools.evidence_for(hood[0]["relation_id"])
    assert evidence["evidence"][0]["excerpt"] == "LightRAG uses PostgreSQL"
    assert tools.get_entity("tool:pg")["name"] == "PostgreSQL"


# --------------------------------------------------------------------------- transport + auth

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(c, method, params=None, token=READ, rid=1):
    headers = {**HEADERS, **({"Authorization": f"Bearer {token}"} if token else {})}
    return c.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, headers=headers)


def bearer_policy():
    return AuthPolicy(mode="bearer", token_scopes=(
        (READ, frozenset({"read:knowledge"})),
        (PROJECT, frozenset({"read:knowledge", "project:7f0c7c5e-0000-4000-8000-000000000001"})),
        (WRITE_ONLY, frozenset({"write:knowledge"})),
    ))


def test_stateless_http_initialize_list_and_call(factory):
    app = build_app(factory, bearer_policy())
    with TestClient(app, base_url="http://localhost:8765") as c:
        init = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}})
        assert init.status_code == 200 and init.headers["content-type"].startswith("application/json")
        assert "mcp-session-id" not in {k.lower() for k in init.headers}  # stateless: no session
        assert init.json()["result"]["serverInfo"]["name"] == "sion-knowledge"

        listed = rpc(c, "tools/list", rid=2).json()["result"]["tools"]
        names = {t["name"] for t in listed}
        assert names == {"search", "fetch", "law_search", "law_article", "law_refs", "get_entity", "neighbors", "evidence_for"}
        assert all(t["annotations"]["readOnlyHint"] is True for t in listed)

        called = rpc(c, "tools/call", {"name": "search", "arguments": {"query": "건폐율"}}, rid=3).json()["result"]
        payload = called.get("structuredContent") or json.loads(called["content"][0]["text"])
        assert payload["results"][0]["id"] == "law:001823:55"


def test_auth_refuses_missing_wrong_and_project_scoped_tokens(factory):
    app = build_app(factory, bearer_policy())
    with TestClient(app, base_url="http://localhost:8765") as c:
        for token in (None, "not-a-real-token-at-all", PROJECT, WRITE_ONLY):
            r = rpc(c, "tools/list", token=token)
            assert r.status_code == 401, token
        challenge = r.headers["www-authenticate"]
        assert 'resource_metadata="http://localhost:8765/.well-known/oauth-protected-resource"' in challenge
        meta = c.get("/.well-known/oauth-protected-resource").json()
        assert meta["resource"] == "http://localhost:8765/mcp" and meta["scopes_supported"] == ["read:knowledge"]


def test_local_only_mode_admits_loopback_and_advertises_the_authorization_server(factory, monkeypatch):
    monkeypatch.setenv("SION_MCP_AUTHORIZATION_SERVER", "https://auth.example.test")
    monkeypatch.setenv("SION_MCP_PUBLIC_URL", "https://kb.example.test")
    app = build_app(factory, AuthPolicy(mode="local-only"))
    with TestClient(app, base_url="http://localhost:8765", client=("127.0.0.1", 50000)) as c:
        assert rpc(c, "tools/list", token=None).status_code == 200
        meta = c.get("/.well-known/oauth-protected-resource").json()
        assert meta == {"resource": "https://kb.example.test/mcp", "scopes_supported": ["read:knowledge"],
                        "bearer_methods_supported": ["header"], "authorization_servers": ["https://auth.example.test"]}
    remote = build_app(factory, AuthPolicy(mode="local-only"))  # a session manager runs once per app
    with TestClient(remote, base_url="http://kb.example.test", client=("203.0.113.9", 50000)) as c:
        assert rpc(c, "tools/list", token=None).status_code == 401


def test_2026_07_28_stateless_requests_and_tool_errors(factory):
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
    headers = {**HEADERS, "MCP-Protocol-Version": "2026-07-28", "Authorization": f"Bearer {READ}"}
    app = build_app(factory, bearer_policy())
    with TestClient(app, base_url="http://localhost:8765") as c:
        # no initialize: every request carries its own protocol envelope
        listed = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}},
                        headers={**headers, "Mcp-Method": "tools/list"})
        assert listed.status_code == 200 and len(listed.json()["result"]["tools"]) == 8
        missing = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "_meta": meta, "name": "get_entity", "arguments": {"key_or_name": "nope"}}},
            headers={**headers, "Mcp-Method": "tools/call", "Mcp-Name": "get_entity"}).json()["result"]
        assert missing["isError"] is True and "no entity with stable_key or name 'nope'" in missing["content"][0]["text"]
