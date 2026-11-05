"""Issue #71 step G (automated part): MCP review flow end-to-end over the Sion HTTP API.

There is no MCP server for Sion knowledge yet: ``packages/aec`` serves only the AEC/CAIR gateway
(``aec_intelligence.mcp_stdio`` / ``mcp_http``). This test therefore drives the HTTP API that a
Sion MCP adapter would call, through an in-process, hermetic stand-in for that adapter:

    remote client (ChatGPT-like) -> MCP JSON-RPC ``tools/call`` -> adapter -> FastAPI TestClient

Scenario: authenticated client -> project selection -> evidence read -> human review decision ->
read the recorded decision back, with a read-only credential and a separate write credential.

What is enforced where (keep this honest when a real adapter lands):

* Server (``sion_api``): bearer token -> scope check. A read-only token cannot write (403), no
  token is 401, and candidates only change state through an explicit human decision call.
* Adapter (this test's stand-in): per-credential project allowlist, checked *before* any HTTP
  call, plus a required ``human_confirmed`` flag on decisions. The API has no project ACL yet
  (Issue #71 step C); until it does, a real adapter must keep this gate and these tests must stay.

The manual ChatGPT iOS OAuth checklist that cannot be automated lives in
``docs/mcp/CHATGPT-MCP-E2E-CHECKLIST.ko.md``.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

# Synthetic test credentials (never real secrets). Separate tokens per role and purpose.
SEED_TOKEN = "seed-token-e2e-0000000001"  # fixture setup only, not used by the "MCP client"
READ_TOKEN = "read-token-e2e-0000000002"
WRITE_TOKEN = "write-token-e2e-000000003"
REMOTE_PEER = ("203.0.113.10", 44321)  # TEST-NET-3: a remote client, so no loopback bypass applies


# --------------------------------------------------------------------------------------------
# Hermetic stand-in for a Sion MCP adapter
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class McpCredential:
    """What an OAuth-authenticated MCP session resolves to: a bearer token and a project ACL."""

    token: str
    projects: frozenset[str]


@dataclass
class RecordingHttp:
    """Wraps the in-process TestClient and records every request the adapter makes."""

    client: TestClient
    calls: list[tuple[str, str]] = field(default_factory=list)

    def request(self, method: str, path: str, token: str, **kwargs: Any):
        self.calls.append((method, path))
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)


class ToolError(Exception):
    def __init__(self, code: int, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


ACL_DENIED = -32001
UPSTREAM_DENIED = -32003
CONFIRMATION_REQUIRED = -32004


class SionMcpAdapter:
    """Minimal MCP tools surface over the Sion HTTP API (JSON-RPC 2.0 messages in and out)."""

    TOOLS = (
        "sion.list_projects",
        "sion.select_project",
        "sion.list_candidates",
        "sion.read_evidence",
        "sion.decide_candidate",
        "sion.read_decision",
    )

    def __init__(self, http: RecordingHttp, credential: McpCredential) -> None:
        self.http = http
        self.credential = credential

    # -- JSON-RPC boundary ---------------------------------------------------------------------
    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        rid = message.get("id")
        if message.get("method") == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": n} for n in self.TOOLS]}}
        if message.get("method") != "tools/call":
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}
        params = message.get("params") or {}
        name = params.get("name")
        if name not in self.TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name!r}"}}
        try:
            payload = getattr(self, "_" + name.split(".", 1)[1])(**(params.get("arguments") or {}))
        except ToolError as exc:
            data = {"http_status": exc.status} if exc.status is not None else None
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": exc.code, "message": str(exc), "data": data}}
        text = json.dumps(payload, ensure_ascii=False)
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": False}}

    # -- helpers -------------------------------------------------------------------------------
    def _require_project(self, project_id: str) -> None:
        # Fail closed before any data access: no HTTP request is made for a disallowed project.
        if project_id not in self.credential.projects:
            raise ToolError(ACL_DENIED, "project is not allowed for this credential")

    def _get(self, path: str, **kwargs: Any) -> Any:
        response = self.http.request("GET", path, self.credential.token, **kwargs)
        if response.status_code != 200:
            raise ToolError(UPSTREAM_DENIED, response.json().get("detail", "request failed"), response.status_code)
        return response.json()

    def _candidate_in_project(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        detail = self._get(f"/api/v1/relations/candidates/{candidate_id}")
        if (detail.get("provenance") or {}).get("project_id") != project_id:
            # Same answer as "not found": do not reveal another project's candidate.
            raise ToolError(ACL_DENIED, "candidate not found in the selected project")
        return detail

    # -- tools ---------------------------------------------------------------------------------
    def _list_projects(self) -> list[dict[str, Any]]:
        rows = self._get("/api/v1/entities", params={"limit": 1000})
        return [
            {"id": r["id"], "name": r["name"]}
            for r in rows
            if r["entity_type_id"] == "Project" and r["id"] in self.credential.projects
        ]

    def _select_project(self, project_id: str) -> dict[str, Any]:
        self._require_project(project_id)
        row = self._get(f"/api/v1/entities/{project_id}")
        if row["entity_type_id"] != "Project":
            raise ToolError(ACL_DENIED, "not a project")
        return {"id": row["id"], "name": row["name"]}

    def _list_candidates(self, project_id: str, status: str = "pending") -> list[dict[str, Any]]:
        self._require_project(project_id)
        body = self._get("/api/v1/relations/candidates", params={"status": status, "limit": 1000})
        return [
            {"id": c["id"], "status": c["status"], "confidence": c["confidence"], "evidence_count": c["evidence_count"]}
            for c in body["candidates"]
            if (c.get("provenance") or {}).get("project_id") == project_id
        ]

    def _read_evidence(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        self._require_project(project_id)
        detail = self._candidate_in_project(project_id, candidate_id)
        return {"id": detail["id"], "status": detail["status"], "evidence": detail["evidence"]}

    def _decide_candidate(
        self,
        project_id: str,
        candidate_id: str,
        decision: str,
        note: str,
        reviewer: str,
        human_confirmed: bool = False,
    ) -> dict[str, Any]:
        self._require_project(project_id)
        # The model may propose; only an explicit human confirmation is forwarded as a decision.
        if human_confirmed is not True or not (note or "").strip() or decision not in {"approve", "reject"}:
            raise ToolError(CONFIRMATION_REQUIRED, "a human-confirmed approve/reject with a note is required")
        self._candidate_in_project(project_id, candidate_id)
        response = self.http.request(
            "POST",
            f"/api/v1/relations/candidates/{candidate_id}/{decision}",
            self.credential.token,
            json={"reviewer": reviewer, "note": note},
        )
        if response.status_code != 200:
            raise ToolError(UPSTREAM_DENIED, response.json().get("detail", "request failed"), response.status_code)
        body = response.json()
        return {"id": body["id"], "status": body["status"], "review": body["review"]}

    def _read_decision(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        self._require_project(project_id)
        detail = self._candidate_in_project(project_id, candidate_id)
        return {
            "id": detail["id"],
            "status": detail["status"],
            "verification_state": detail["verification_state"],
            "review": detail["review"],
            "evidence_states": sorted({e["verification_state"] for e in detail["evidence"]}),
        }


class McpSession:
    """Client side: builds JSON-RPC ``tools/call`` messages and unwraps the text content."""

    def __init__(self, adapter: SionMcpAdapter) -> None:
        self.adapter = adapter
        self._ids = itertools.count(1)

    def raw(self, name: str, **arguments: Any) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        response = self.adapter.handle(message)
        assert response["jsonrpc"] == "2.0" and response["id"] == message["id"]
        return response

    def call(self, name: str, **arguments: Any) -> Any:
        response = self.raw(name, **arguments)
        assert "error" not in response, response
        return json.loads(response["result"]["content"][0]["text"])

    def error(self, name: str, **arguments: Any) -> dict[str, Any]:
        response = self.raw(name, **arguments)
        assert "error" in response, response
        return response["error"]


# --------------------------------------------------------------------------------------------
# Fixture: two projects, each with pending candidates and evidence
# --------------------------------------------------------------------------------------------


@dataclass
class World:
    http: RecordingHttp
    project_a: str
    project_b: str
    candidates_a: list[str]
    candidates_b: list[str]

    def session(self, token: str, projects: set[str]) -> McpSession:
        return McpSession(SionMcpAdapter(self.http, McpCredential(token, frozenset(projects))))

    def counts(self) -> dict[str, int]:
        response = self.http.client.get(
            "/api/v1/relations/candidates", params={"status": "all"}, headers={"Authorization": f"Bearer {SEED_TOKEN}"}
        )
        return response.json()["counts"]


def _seed(c: TestClient) -> tuple[str, str, list[str], list[str]]:
    auth = {"Authorization": f"Bearer {SEED_TOKEN}"}

    def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = c.post(path, json=body, headers=auth)
        assert response.status_code == 201, response.text
        return response.json()

    projects: list[str] = []
    candidates: list[list[str]] = []
    for code in ("a", "b"):
        project = post("/api/v1/entities", {"stable_key": f"e2e:project:{code}", "entity_type_id": "Project", "name": f"E2E project {code.upper()}"})
        projects.append(project["id"])
        wall = post("/api/v1/entities", {"stable_key": f"e2e:{code}:wall", "entity_type_id": "Concept", "name": f"wall {code}"})
        slab = post("/api/v1/entities", {"stable_key": f"e2e:{code}:slab", "entity_type_id": "Concept", "name": f"slab {code}"})
        ids = []
        # A high-confidence candidate is deliberately included: confidence alone must never approve.
        for idx, confidence in enumerate((0.99, 0.55)):
            relation = post(
                "/api/v1/relations",
                {
                    "stable_key": f"e2e:{code}:candidate:{idx}",
                    "source_entity_id": wall["id"],
                    "target_entity_id": slab["id"],
                    "relation_type_id": "SUPPORTS" if idx == 0 else "CONNECTS_TO",
                    "confidence": confidence,
                    "source_kind": "inferred",
                    "properties": {
                        "candidate": True,
                        "extractor": "e2e-fixture",
                        "provenance": {"project_id": project["id"], "source_file": f"sheet-{code}-{idx}.pdf"},
                    },
                },
            )
            post(
                "/api/v1/evidence",
                {
                    "relation_id": relation["id"],
                    "source_uri": f"urn:e2e:{code}:sheet-{idx}",
                    "source_locator": "page=1",
                    "confidence": confidence,
                    "extractor": "e2e-fixture",
                    "properties": {"excerpt": f"synthetic excerpt {code}{idx}"},
                },
            )
            ids.append(relation["id"])
        candidates.append(ids)
    return projects[0], projects[1], candidates[0], candidates[1]


@pytest.fixture
def world():
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (SEED_TOKEN, frozenset({"read:knowledge", "write:knowledge"})),
            (READ_TOKEN, frozenset({"read:knowledge"})),
            (WRITE_TOKEN, frozenset({"read:knowledge", "write:knowledge"})),
        ),
    )
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)
    with TestClient(app, base_url="http://sion.example.test", client=REMOTE_PEER) as c:
        project_a, project_b, cand_a, cand_b = _seed(c)
        yield World(RecordingHttp(c), project_a, project_b, cand_a, cand_b)


# --------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------


def test_full_flow_read_and_write_with_separate_credentials(world: World):
    reader = world.session(READ_TOKEN, {world.project_a})
    writer = world.session(WRITE_TOKEN, {world.project_a})

    # 1. authenticated client discovers tools and only its allowed projects
    tools = reader.adapter.handle({"jsonrpc": "2.0", "id": 0, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == set(SionMcpAdapter.TOOLS)
    assert [p["id"] for p in reader.call("sion.list_projects")] == [world.project_a]

    # 2. project selection
    assert reader.call("sion.select_project", project_id=world.project_a)["name"] == "E2E project A"

    # 3. evidence read (read-only credential)
    pending = reader.call("sion.list_candidates", project_id=world.project_a)
    assert {c["id"] for c in pending} == set(world.candidates_a)
    assert all(c["status"] == "pending" for c in pending)
    target = world.candidates_a[1]  # the low-confidence one; a human decides, not the score
    evidence = reader.call("sion.read_evidence", project_id=world.project_a, candidate_id=target)
    assert evidence["status"] == "pending"
    assert [e["source_locator"] for e in evidence["evidence"]] == ["page=1"]
    assert evidence["evidence"][0]["excerpt"] == "synthetic excerpt a1"

    # 4. the read credential cannot record the decision; the server refuses it (403) and nothing changes
    before = world.counts()
    denied = reader.error(
        "sion.decide_candidate", project_id=world.project_a, candidate_id=target,
        decision="approve", note="checked sheet a-1", reviewer="reviewer-1", human_confirmed=True,
    )
    assert denied["code"] == UPSTREAM_DENIED and denied["data"]["http_status"] == 403
    assert world.counts() == before

    # 5. human review decision through the separate write credential
    decided = writer.call(
        "sion.decide_candidate", project_id=world.project_a, candidate_id=target,
        decision="approve", note="checked sheet a-1", reviewer="reviewer-1", human_confirmed=True,
    )
    assert decided["status"] == "approved"

    # 6. read the recorded decision back with the read-only credential
    record = reader.call("sion.read_decision", project_id=world.project_a, candidate_id=target)
    assert record["status"] == "approved" and record["verification_state"] == "human_verified"
    review = record["review"]
    assert review["decision"] == "approved" and review["reviewer"] == "reviewer-1"
    assert review["note"] == "checked sheet a-1" and review["previous_state"] == "unverified"
    assert review["decided_at"]
    assert record["evidence_states"] == ["human_verified"]

    # exactly one candidate moved, the one the human decided
    assert world.counts() == {"pending": before["pending"] - 1, "approved": 1, "rejected": 0}
    assert reader.call("sion.read_decision", project_id=world.project_a, candidate_id=world.candidates_a[0])["status"] == "pending"

    # a second decision on the same candidate is refused (no silent overwrite of the record)
    again = writer.error(
        "sion.decide_candidate", project_id=world.project_a, candidate_id=target,
        decision="reject", note="changed mind", reviewer="reviewer-2", human_confirmed=True,
    )
    assert again["data"]["http_status"] == 409
    assert reader.call("sion.read_decision", project_id=world.project_a, candidate_id=target)["review"]["reviewer"] == "reviewer-1"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_read_only_token_cannot_write_any_review_route(world: World, action: str):
    """Server-side guarantee, independent of the adapter: read scope never writes."""
    c = world.http.client
    read = {"Authorization": f"Bearer {READ_TOKEN}"}
    rid = world.candidates_a[0]
    before = world.counts()
    assert c.post(f"/api/v1/relations/candidates/{rid}/{action}", json={"note": "x"}, headers=read).status_code == 403
    assert c.post(f"/api/v1/relations/candidates/{rid}/{action}", json={"note": "x"}).status_code == 401
    bulk = {"ids": [rid], "decision": action, "note": "x"}
    assert c.post("/api/v1/relations/candidates/bulk", json=bulk, headers=read).status_code == 403
    assert c.post(f"/api/v1/relations/candidates/{rid}/reopen", json={"note": "x"}, headers=read).status_code == 403
    assert c.post(
        "/api/v1/evidence", json={"relation_id": rid, "source_uri": "urn:x"}, headers=read
    ).status_code == 403
    wrong = {"Authorization": "Bearer not-a-registered-token-000"}
    assert c.post(f"/api/v1/relations/candidates/{rid}/{action}", json={"note": "x"}, headers=wrong).status_code == 401
    assert world.counts() == before == {"pending": 4, "approved": 0, "rejected": 0}


@pytest.mark.parametrize(
    "tool,extra",
    [
        ("sion.select_project", {}),
        ("sion.list_candidates", {}),
        ("sion.read_evidence", {"candidate_id": "CAND_B0"}),
        ("sion.read_decision", {"candidate_id": "CAND_B0"}),
        (
            "sion.decide_candidate",
            {"candidate_id": "CAND_B0", "decision": "approve", "note": "n", "reviewer": "r", "human_confirmed": True},
        ),
    ],
)
def test_disallowed_project_rejected_before_data_access(world: World, tool: str, extra: dict[str, Any]):
    # Even the write credential is confined to its project allowlist.
    session = world.session(WRITE_TOKEN, {world.project_a})
    arguments = {k: (world.candidates_b[0] if v == "CAND_B0" else v) for k, v in extra.items()}
    before_calls = len(world.http.calls)
    before = world.counts()
    error = session.error(tool, project_id=world.project_b, **arguments)
    assert error["code"] == ACL_DENIED
    assert world.http.calls[before_calls:] == []  # rejected before any API/data access
    assert world.counts() == before
    assert world.project_b not in {p["id"] for p in session.call("sion.list_projects")}


def test_candidate_from_another_project_is_not_reachable_through_allowed_project(world: World):
    reader = world.session(READ_TOKEN, {world.project_a})
    writer = world.session(WRITE_TOKEN, {world.project_a})
    foreign = world.candidates_b[0]
    assert reader.error("sion.read_evidence", project_id=world.project_a, candidate_id=foreign)["code"] == ACL_DENIED
    before = world.counts()
    error = writer.error(
        "sion.decide_candidate", project_id=world.project_a, candidate_id=foreign,
        decision="approve", note="n", reviewer="r", human_confirmed=True,
    )
    assert error["code"] == ACL_DENIED
    assert not [c for c in world.http.calls if c[0] == "POST"]
    assert world.counts() == before
    assert {c["id"] for c in reader.call("sion.list_candidates", project_id=world.project_a)} == set(world.candidates_a)


def test_no_candidate_is_auto_approved(world: World):
    reader = world.session(READ_TOKEN, {world.project_a, world.project_b})
    writer = world.session(WRITE_TOKEN, {world.project_a, world.project_b})

    # Reading everything, including the 0.99-confidence candidates, changes no state.
    for project, ids in ((world.project_a, world.candidates_a), (world.project_b, world.candidates_b)):
        reader.call("sion.select_project", project_id=project)
        for cid in ids:
            reader.call("sion.read_evidence", project_id=project, candidate_id=cid)
            reader.call("sion.read_decision", project_id=project, candidate_id=cid)
    assert world.counts() == {"pending": 4, "approved": 0, "rejected": 0}

    # A write-capable session still cannot decide without an explicit human confirmation and note.
    target = world.candidates_a[0]
    for kwargs in (
        {"decision": "approve", "note": "auto", "reviewer": "model"},
        {"decision": "approve", "note": "auto", "reviewer": "model", "human_confirmed": "yes"},
        {"decision": "approve", "note": "   ", "reviewer": "model", "human_confirmed": True},
        {"decision": "auto", "note": "auto", "reviewer": "model", "human_confirmed": True},
    ):
        error = writer.error("sion.decide_candidate", project_id=world.project_a, candidate_id=target, **kwargs)
        assert error["code"] == CONFIRMATION_REQUIRED
    assert not [c for c in world.http.calls if c[0] == "POST"]
    assert world.counts() == {"pending": 4, "approved": 0, "rejected": 0}

    # After one human rejection, every non-pending candidate carries a human review record.
    writer.call(
        "sion.decide_candidate", project_id=world.project_b, candidate_id=world.candidates_b[0],
        decision="reject", note="co-occurrence only", reviewer="reviewer-1", human_confirmed=True,
    )
    assert world.counts() == {"pending": 3, "approved": 0, "rejected": 1}
    for project, ids in ((world.project_a, world.candidates_a), (world.project_b, world.candidates_b)):
        for cid in ids:
            record = reader.call("sion.read_decision", project_id=project, candidate_id=cid)
            if record["status"] != "pending":
                assert record["review"]["reviewer"] == "reviewer-1" and record["review"]["note"]
            else:
                assert record["review"] is None and record["evidence_states"] == ["unverified"]
