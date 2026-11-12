"""Remote MCP server for the knowledge core: stateless Streamable HTTP, read-only tools.

One process, no sessions: every request is a self-contained JSON-RPC call answered with JSON
(``stateless_http=True, json_response=True``), so it scales behind any load balancer and fits the
2026-07 MCP specification's stateless transport. Built on the official Python SDK (``mcp`` 2.x,
``MCPServer``); install the ``mcp`` extra and run ``sion-mcp``.

Tools (all read-only, ``readOnlyHint``):

* ``search`` / ``fetch``  the two tools ChatGPT connectors and deep research expect: search returns
  ``{results: [{id, title, url}]}``, fetch returns ``{id, title, text, url, metadata}``. Ids are
  ``law:<law_id>:<article_key>`` and ``entity:<stable_key>``.
* ``law_search``, ``law_article``, ``law_refs``  the law-knowledge API with ``as_of``.
* ``get_entity``, ``neighbors``, ``evidence_for``  the curated graph. Review candidates
  (unverified, ``properties.candidate``) are hidden unless asked for, and always labelled.

Authentication reuses the API's bearer tokens (``SION_API_TOKENS_JSON``): a request needs a token
with ``read:knowledge`` (or ``*``). Project-restricted tokens are refused, because these tools are
not project-scoped. Without bearer mode the server only listens on loopback. When
``SION_MCP_AUTHORIZATION_SERVER`` is set, ``/.well-known/oauth-protected-resource`` advertises it
(RFC 9728) so OAuth clients can discover where to get a token; verifying tokens from that server
is the SaaS phase's job.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from . import models
from .auth import AuthPolicy
from .law_knowledge import LawArticle, _out, article_refs, parse_article_key
from .law_search import HybridOptions, embedder_from_env, hybrid_search

READ_SCOPE = "read:knowledge"
MAX_TEXT = 20000


def _today(as_of: str | None) -> date:
    return date.fromisoformat(as_of) if as_of else date.today()


def _public_url() -> str:
    return os.getenv("SION_MCP_PUBLIC_URL", "").rstrip("/")


def _law_uri(a: dict) -> str:
    return a.get("source_url") or f"{_public_url()}/api/v1/law/articles/{a['law_id']}/{a['article_key']}"


def _entity_out(e: models.Entity) -> dict[str, Any]:
    return {"id": str(e.id), "stable_key": e.stable_key, "type": e.entity_type_id, "name": e.name,
            "description": e.description, "category": e.category, "external_uri": e.external_uri,
            "aliases": (e.properties or {}).get("aliases", []) if isinstance(e.properties, dict) else []}


def _is_candidate(r: models.Relation) -> bool:
    return bool((r.properties or {}).get("candidate")) or r.verification_state in {"unverified", "rejected"}


class KnowledgeTools:
    """The tool bodies, independent of the transport so they are testable without MCP."""

    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory

    # ------------------------------------------------------------------ search / fetch

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        limit = max(1, min(limit, 20))
        results: list[dict[str, str]] = []
        with self.factory() as s:
            embedder, model = embedder_from_env()
            law = hybrid_search(s, query, limit=limit, options=HybridOptions(embedder=embedder, embed_model=model))
            for r in law["results"]:
                results.append({"id": f"law:{r['law_id']}:{r['article_key']}", "title": f"{r['citation']} {r['title'] or ''}".strip(),
                                "url": _law_uri(r)})
            like = f"%{query.strip()}%"
            for e in s.scalars(select(models.Entity).where(
                    or_(models.Entity.name.ilike(like), models.Entity.description.ilike(like))).limit(limit)):
                results.append({"id": f"entity:{e.stable_key}", "title": f"{e.name} ({e.entity_type_id})",
                                "url": e.external_uri or f"{_public_url()}/api/v1/entities/{e.id}"})
        return {"results": results[: limit * 2]}

    def fetch(self, id: str) -> dict[str, Any]:  # noqa: A002 - the tool contract names it ``id``
        kind, _, rest = id.partition(":")
        with self.factory() as s:
            if kind == "law":
                law_id, _, key = rest.rpartition(":")
                a = self._article(s, law_id, key, None)
                text = a["text"][:MAX_TEXT]
                return {"id": id, "title": f"{a['law_name']} {a['article_label']} {a['title'] or ''}".strip(),
                        "text": text, "url": _law_uri(a),
                        "metadata": {k: a[k] for k in ("law_id", "effective_from", "effective_to", "content_hash", "refs")}}
            if kind == "entity":
                e = s.scalar(select(models.Entity).where(models.Entity.stable_key == rest))
                if e is None:
                    raise ValueError(f"no entity {rest}")
                hood = self._neighbors(s, e, None, False, 50)
                lines = [f"{e.name} ({e.entity_type_id})", e.description or ""]
                lines += [f"- {n['direction']} {n['relation']} {n['entity']['name']}" for n in hood]
                return {"id": id, "title": e.name, "text": "\n".join(x for x in lines if x)[:MAX_TEXT],
                        "url": e.external_uri or f"{_public_url()}/api/v1/entities/{e.id}",
                        "metadata": {"type": e.entity_type_id, "stable_key": e.stable_key, "relations": len(hood)}}
        raise ValueError("id must start with law: or entity:")

    # ------------------------------------------------------------------ law

    @staticmethod
    def _article(s: Session, law_id: str, article: str, as_of: str | None) -> dict[str, Any]:
        key = parse_article_key(article)
        day = _today(as_of)
        row = s.scalar(select(LawArticle).where(
            LawArticle.law_id == law_id, LawArticle.article_key == key, LawArticle.effective_from <= day,
            or_(LawArticle.effective_to.is_(None), LawArticle.effective_to >= day),
        ).order_by(LawArticle.effective_from.desc()).limit(1))
        if row is None:
            raise ValueError(f"no version of {law_id} {article} in force on {day.isoformat()}")
        return _out(row)

    def law_search(self, query: str, law: str | None = None, as_of: str | None = None, limit: int = 10) -> dict[str, Any]:
        with self.factory() as s:
            embedder, model = embedder_from_env()
            return hybrid_search(s, query, law=law, as_of=_today(as_of), limit=max(1, min(limit, 50)),
                                 options=HybridOptions(embedder=embedder, embed_model=model))

    def law_article(self, law_id: str, article: str, as_of: str | None = None) -> dict[str, Any]:
        with self.factory() as s:
            return self._article(s, law_id, article, as_of)

    def law_refs(self, law_id: str, article: str, as_of: str | None = None) -> dict[str, Any]:
        with self.factory() as s:
            return article_refs(s, law_id, parse_article_key(article), _today(as_of))

    # ------------------------------------------------------------------ graph

    @staticmethod
    def _entity(s: Session, key_or_name: str) -> models.Entity:
        e = s.scalar(select(models.Entity).where(models.Entity.stable_key == key_or_name))
        if e is None:
            e = s.scalar(select(models.Entity).where(models.Entity.name == key_or_name).order_by(models.Entity.stable_key))
        if e is None:
            raise ValueError(f"no entity with stable_key or name {key_or_name!r}")
        return e

    @staticmethod
    def _neighbors(s: Session, e: models.Entity, relation_type: str | None, include_candidates: bool,
                   limit: int) -> list[dict[str, Any]]:
        stmt = select(models.Relation).where(or_(models.Relation.source_entity_id == e.id,
                                                 models.Relation.target_entity_id == e.id))
        if relation_type:
            stmt = stmt.where(models.Relation.relation_type_id == relation_type)
        out = []
        for r in s.scalars(stmt.order_by(models.Relation.stable_key)):
            candidate = _is_candidate(r)
            if r.valid_to is not None or (candidate and not include_candidates):
                continue
            outgoing = r.source_entity_id == e.id
            other = s.get(models.Entity, r.target_entity_id if outgoing else r.source_entity_id)
            out.append({"relation_id": str(r.id), "relation": r.relation_type_id,
                        "direction": "out" if outgoing else "in", "entity": _entity_out(other),
                        "verification_state": r.verification_state, "candidate": candidate,
                        "confidence": r.confidence})
            if len(out) >= limit:
                break
        return out

    def get_entity(self, key_or_name: str) -> dict[str, Any]:
        with self.factory() as s:
            return _entity_out(self._entity(s, key_or_name))

    def neighbors(self, key_or_name: str, relation_type: str | None = None, include_candidates: bool = False,
                  limit: int = 50) -> dict[str, Any]:
        with self.factory() as s:
            e = self._entity(s, key_or_name)
            return {"entity": _entity_out(e),
                    "neighbors": self._neighbors(s, e, relation_type, include_candidates, max(1, min(limit, 200)))}

    def evidence_for(self, relation_id: str) -> dict[str, Any]:
        import uuid

        with self.factory() as s:
            r = s.get(models.Relation, uuid.UUID(relation_id))
            if r is None:
                raise ValueError(f"no relation {relation_id}")
            rows = s.scalars(select(models.Evidence).where(models.Evidence.relation_id == r.id)).all()
            return {"relation_id": relation_id, "relation": r.relation_type_id,
                    "verification_state": r.verification_state, "candidate": _is_candidate(r),
                    "evidence": [{"source_uri": ev.source_uri, "locator": ev.source_locator,
                                  "excerpt": (ev.properties or {}).get("excerpt"), "excerpt_hash": ev.excerpt_hash,
                                  "extractor": ev.extractor, "model": ev.model,
                                  "verification_state": ev.verification_state} for ev in rows]}


INSTRUCTIONS = (
    "Sion knowledge core: Korean building-law articles (versioned by effective date) and a curated "
    "ontology graph with evidence. Use search/fetch for discovery, law_search/law_article/law_refs "
    "with as_of (YYYY-MM-DD) for the text in force on a date, and neighbors/evidence_for for graph "
    "facts. Unverified review candidates are hidden unless include_candidates is true. Cite the "
    "citation and content_hash of articles you rely on; search results are not legal conclusions."
)


def build_server(factory: sessionmaker[Session]):
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    tools = KnowledgeTools(factory)
    server = MCPServer(name="sion-knowledge", title="Sion knowledge core", instructions=INSTRUCTIONS,
                       version="0.3.0")
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    docs = {
        "search": "Search law articles and graph entities. Returns ids for fetch.",
        "fetch": "Full text and metadata for an id from search (law:<law_id>:<article> or entity:<stable_key>).",
        "law_search": "Hybrid search over law articles in force on as_of (default today).",
        "law_article": "One law article (accepts 61, 61-2 or 제61조의2) in force on as_of.",
        "law_refs": "Articles this article cites and articles citing it, as of a date.",
        "get_entity": "A graph entity by stable_key or exact name.",
        "neighbors": "Relations of an entity. Review candidates only when include_candidates is true.",
        "evidence_for": "Evidence rows (source, locator, excerpt) behind a relation.",
    }
    for name, description in docs.items():
        server.add_tool(_client_errors(getattr(tools, name), ToolError), name=name, description=description,
                        annotations=read_only)
    return server


def _client_errors(fn, tool_error):
    """Report bad arguments (unknown id, article not in force, ...) to the client as a tool error."""
    import functools

    from fastapi import HTTPException

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise tool_error(str(exc)) from exc
        except HTTPException as exc:
            raise tool_error(str(exc.detail)) from exc

    return wrapper


def _authorized(policy: AuthPolicy, authorization: str | None) -> bool:
    principal = policy._principal_for_authorization(authorization)  # noqa: SLF001 - shared token table
    if principal is None:
        return False
    if principal.projects is not None and "*" not in principal.scopes:
        return False  # these tools are not project-scoped
    return "*" in principal.scopes or READ_SCOPE in principal.scopes


def build_app(factory: sessionmaker[Session] | None = None, policy: AuthPolicy | None = None, *, path: str = "/mcp"):
    """ASGI app: the MCP endpoint behind bearer auth, plus protected-resource metadata."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from .config import load_settings
    from .db import build_engine, build_session_factory

    if factory is None:
        factory = build_session_factory(build_engine(load_settings().database_url))
    policy = policy or AuthPolicy.from_env()
    app = build_server(factory).streamable_http_app(streamable_http_path=path, stateless_http=True, json_response=True)
    resource = _public_url() + path if _public_url() else None
    authorization_server = os.getenv("SION_MCP_AUTHORIZATION_SERVER")
    metadata_path = "/.well-known/oauth-protected-resource"

    async def protected_resource(request):
        body = {"resource": resource or str(request.url.replace(path=path, query="")),
                "scopes_supported": [READ_SCOPE], "bearer_methods_supported": ["header"]}
        if authorization_server:
            body["authorization_servers"] = [authorization_server]
        return JSONResponse(body)

    app.add_route(metadata_path, protected_resource, methods=["GET"])
    app.add_route(metadata_path + path, protected_resource, methods=["GET"])
    bearer = policy.mode in {"bearer", "local-or-bearer"}

    class BearerGate:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or not scope["path"].startswith(path):
                return await self.inner(scope, receive, send)
            request = Request(scope)
            ok = bearer and _authorized(policy, request.headers.get("authorization"))
            if not ok and policy.mode in {"local-only", "local-or-bearer"}:
                # loopback peer AND a localhost Host header AND no cross-site origin, as in the API
                ok = policy._trusted_local_request(request)  # noqa: SLF001
            if ok:
                return await self.inner(scope, receive, send)
            base = resource.rsplit(path, 1)[0] if resource else str(request.base_url).rstrip("/")
            meta = base + metadata_path
            challenge = f'Bearer resource_metadata="{meta}", scope="{READ_SCOPE}"'
            response = JSONResponse({"error": "unauthorized", "detail": f"a bearer token with {READ_SCOPE} is required"},
                                    status_code=401, headers={"WWW-Authenticate": challenge})
            return await response(scope, receive, send)

    app.add_middleware(BearerGate)
    return app


def main(argv: list[str] | None = None) -> int:
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(prog="sion-mcp", description="Remote MCP server for the Sion knowledge core")
    p.add_argument("--host", default=os.getenv("SION_MCP_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("SION_MCP_PORT", "8765")))
    args = p.parse_args(argv)
    policy = AuthPolicy.from_env()
    if args.host not in {"127.0.0.1", "::1", "localhost"} and policy.mode == "local-only":
        p.error("binding beyond loopback needs SION_API_AUTH_MODE=bearer (or local-or-bearer) and tokens")
    uvicorn.run(build_app(policy=policy), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
