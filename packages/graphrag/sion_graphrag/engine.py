"""LightRAG engine wrapper: PostgreSQL storage, OpenAI-compatible model endpoints.

LightRAG is an optional dependency (``pip install -e .[graphrag]``). It is only
imported when an engine is started, because importing it can install missing
provider packages at runtime.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session, sessionmaker

from .projection import AUDIT_PROJECTION_REVIEW_STATES, DEFAULT_PROJECTION_REVIEW_STATES, build_custom_kg

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Graph backend for SION_GRAPHRAG_STORAGE=postgres. "table" (default) is LightRAG's
# PGTableGraphStorage: plain indexed tables, no Apache AGE. "age" keeps the legacy
# PGGraphStorage, which LightRAG 1.5.7 refuses on AGE >= 1.8.0; move an existing AGE
# graph with `python -m lightrag.tools.migrate_graph_storage` (see docs/GRAPHRAG.md).
POSTGRES_GRAPH_STORAGES = {
    "table": "PGTableGraphStorage",
    "age": "PGGraphStorage",
}
POSTGRES_STORAGES = {
    "kv_storage": "PGKVStorage",
    "vector_storage": "PGVectorStorage",
    "graph_storage": POSTGRES_GRAPH_STORAGES["table"],
    "doc_status_storage": "PGDocStatusStorage",
}
LOCAL_STORAGES = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": "NetworkXStorage",
    "doc_status_storage": "JsonDocStatusStorage",
}
QUERY_MODES = {"local", "global", "hybrid", "naive", "mix"}
# Open per-project engines kept at once; the least recently used one is finalized first.
DEFAULT_MAX_PROJECT_ENGINES = 32


def project_workspace(base: str, project_id: object) -> str:
    """LightRAG workspace for one project: ``<base>_p_<uuid hex>``.

    LightRAG keys every Postgres row (and every local storage directory) by workspace,
    so a project's chunks, vectors and graph never mix with another project's.
    """
    try:
        token = uuid.UUID(str(project_id)).hex
    except ValueError as exc:
        raise ValueError("project_id must be a UUID") from exc
    if not re.fullmatch(r"[A-Za-z0-9_]+", base):
        raise ValueError("SION_GRAPHRAG_WORKSPACE may contain only letters, digits and '_'")
    return f"{base}_p_{token}"


class GraphRagUnavailable(RuntimeError):
    """LightRAG is not installed or the GraphRAG layer is not configured."""


@dataclass(frozen=True)
class GraphRagConfig:
    workspace: str
    storage: str  # "postgres" (LightRAG reads POSTGRES_* env vars) or "local"
    working_dir: Path
    embedding_model: str
    embedding_dim: int
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # "openai" (OpenAI-compatible endpoint) or "embedhub" (sion_embedhub registry key in embedding_model, e.g. nv-1b)
    embedding_provider: str = "openai"
    # Postgres graph backend: "table" (PGTableGraphStorage, no AGE) or "age" (legacy PGGraphStorage)
    graph_backend: str = "table"

    @classmethod
    def from_env(cls) -> "GraphRagConfig | None":
        model = os.getenv("SION_GRAPHRAG_EMBED_MODEL")
        dim = os.getenv("SION_GRAPHRAG_EMBED_DIM")
        if not model or not dim:
            return None
        storage = os.getenv("SION_GRAPHRAG_STORAGE", "postgres").strip().lower()
        if storage not in {"postgres", "local"}:
            raise ValueError("SION_GRAPHRAG_STORAGE must be 'postgres' or 'local'")
        graph_backend = os.getenv("SION_GRAPHRAG_GRAPH_BACKEND", "table").strip().lower()
        if graph_backend not in POSTGRES_GRAPH_STORAGES:
            raise ValueError("SION_GRAPHRAG_GRAPH_BACKEND must be 'table' or 'age'")
        return cls(
            workspace=os.getenv("SION_GRAPHRAG_WORKSPACE", "sion"),
            storage=storage,
            working_dir=Path(os.getenv("SION_GRAPHRAG_WORKING_DIR", str(PROJECT_ROOT / "runtime" / "graphrag"))),
            embedding_model=model,
            embedding_dim=int(dim),
            embedding_base_url=os.getenv("SION_GRAPHRAG_EMBED_BASE_URL"),
            embedding_api_key=os.getenv("SION_GRAPHRAG_EMBED_API_KEY"),
            llm_model=os.getenv("SION_GRAPHRAG_LLM_MODEL"),
            llm_base_url=os.getenv("SION_GRAPHRAG_LLM_BASE_URL"),
            llm_api_key=os.getenv("SION_GRAPHRAG_LLM_API_KEY"),
            embedding_provider=os.getenv("SION_GRAPHRAG_EMBED_PROVIDER", "openai").strip().lower(),
            graph_backend=graph_backend,
        )

    @property
    def answers_enabled(self) -> bool:
        return bool(self.llm_model)

    @property
    def storages(self) -> dict[str, str]:
        """LightRAG storage class names for this configuration."""
        if self.storage != "postgres":
            return dict(LOCAL_STORAGES)
        if self.graph_backend not in POSTGRES_GRAPH_STORAGES:
            raise ValueError("graph_backend must be 'table' or 'age'")
        return {**POSTGRES_STORAGES, "graph_storage": POSTGRES_GRAPH_STORAGES[self.graph_backend]}


async def _no_llm(*_args: Any, **_kwargs: Any) -> str:
    raise GraphRagUnavailable("no LLM configured; set SION_GRAPHRAG_LLM_MODEL to generate answers")


class SionGraphRag:
    """Rebuildable GraphRAG projection over the canonical Sion graph."""

    def __init__(
        self,
        config: GraphRagConfig,
        *,
        embedding_func: Callable[[list[str]], Awaitable[Any]] | None = None,
        llm_func: Callable[..., Awaitable[str]] | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        self.config = config
        self._tokenizer = tokenizer
        self._embedding_func = embedding_func
        self._llm_func = llm_func
        self._rag = None
        self.project_id: str | None = None
        self._children: OrderedDict[str, SionGraphRag] = OrderedDict()
        self._children_lock = asyncio.Lock()
        self.max_project_engines = DEFAULT_MAX_PROJECT_ENGINES

    async def for_project(self, project_id: object) -> "SionGraphRag":
        """Engine bound to one project's own LightRAG workspace (cached, LRU-bounded)."""
        if self.project_id is not None:
            raise RuntimeError("for_project() is only available on the base engine")
        workspace = project_workspace(self.config.workspace, project_id)
        async with self._children_lock:
            child = self._children.get(workspace)
            if child is None:
                child = SionGraphRag(
                    replace(self.config, workspace=workspace),
                    embedding_func=self._embedding_func,
                    llm_func=self._llm_func,
                    tokenizer=self._tokenizer,
                )
                child.project_id = str(uuid.UUID(str(project_id)))
                self._children[workspace] = child
            self._children.move_to_end(workspace)
            evicted = []
            while len(self._children) > self.max_project_engines:
                evicted.append(self._children.popitem(last=False)[1])
        for old in evicted:
            await old.close()
        return child

    def _build(self):
        try:
            from lightrag import LightRAG
            from lightrag.utils import EmbeddingFunc
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise GraphRagUnavailable("install the 'rag' extra: pip install 'sion-ontology-platform[rag]' (lightrag-hku)") from exc
        config = self.config
        embed = self._embedding_func
        model_name = config.embedding_model
        if embed is None and config.embedding_provider == "embedhub":
            # LightRAG names its vector tables after model_name, so use the real model id (not the registry key):
            # nv-1b @ 1024d keeps reading the tables already written by nvidia/nemotron-3.5-embed-1b.
            from sion_embedhub import Embedder, KeyPool, default_registry
            from sion_embedhub.lightrag import lightrag_embedding_func

            spec = default_registry().get(config.embedding_model)
            embedder = Embedder(spec, KeyPool.from_env("NVIDIA_API_KEY") if spec.provider == "nvidia" else None)
            embed = lightrag_embedding_func(embedder, config.embedding_dim)
            model_name = spec.model
        elif embed is None and config.embedding_provider != "openai":
            raise ValueError("SION_GRAPHRAG_EMBED_PROVIDER must be 'openai' or 'embedhub'")
        if embed is None:
            from lightrag.llm.openai import openai_embed

            async def embed(texts: list[str]):
                return await openai_embed.func(
                    texts,
                    model=config.embedding_model,
                    base_url=config.embedding_base_url,
                    api_key=config.embedding_api_key,
                )

        llm = self._llm_func
        if llm is None and config.answers_enabled:
            from lightrag.llm.openai import openai_complete_if_cache

            async def llm(prompt, system_prompt=None, history_messages=None, **kwargs):
                kwargs.pop("hashing_kv", None)
                return await openai_complete_if_cache(
                    config.llm_model,
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    base_url=config.llm_base_url,
                    api_key=config.llm_api_key,
                    **kwargs,
                )

        storages = config.storages
        config.working_dir.mkdir(parents=True, exist_ok=True)
        extra: dict[str, Any] = {"tokenizer": self._tokenizer} if self._tokenizer is not None else {}
        return LightRAG(
            working_dir=str(config.working_dir),
            workspace=config.workspace,
            embedding_func=EmbeddingFunc(
                embedding_dim=config.embedding_dim,
                func=embed,
                model_name=model_name,
            ),
            llm_model_func=llm or _no_llm,
            **storages,
            **extra,
        )

    def _query_role(self):
        """Asymmetric embedhub models must embed search text as 'query', stored text as 'passage'."""
        if self.config.embedding_provider == "embedhub":
            from sion_embedhub.lightrag import as_query

            return as_query()
        return nullcontext()

    async def start(self) -> None:
        if self._rag is None:
            rag = self._build()
            await rag.initialize_storages()
            self._rag = rag

    async def close(self) -> None:
        children = list(self._children.values())
        self._children.clear()
        for child in children:
            await child.close()
        if self._rag is not None:
            await self._rag.finalize_storages()
            self._rag = None

    async def project(
        self, session_factory: sessionmaker[Session], *, include_rejected: bool = False
    ) -> dict[str, int]:
        """Upsert the default projection, or count the audit projection without indexing it."""
        states = AUDIT_PROJECTION_REVIEW_STATES if include_rejected else DEFAULT_PROJECTION_REVIEW_STATES
        with session_factory() as session:
            custom_kg = build_custom_kg(session, review_states=states, project_id=self.project_id)
        if not include_rejected and custom_kg["chunks"]:
            await self.start()
            await self._rag.ainsert_custom_kg(custom_kg, full_doc_id=f"sion-canonical-{self.config.workspace}")
        return {key: len(value) for key, value in custom_kg.items()}

    async def extract_relation_candidates(
        self, session_factory: sessionmaker[Session], *, max_nodes: int = 1000
    ) -> dict[str, Any]:
        """Store LightRAG-extracted edges between known Sion entities as unverified candidates.

        LightRAG builds its graph from inserted documents with the configured LLM; this
        only reads that graph back. Nothing is promoted without a reviewer.
        """
        from sion_ingestion.relation_extraction import (
            build_gazetteer,
            lightrag_knowledge_graph,
            proposals_from_lightrag,
            store_proposals,
        )

        await self.start()
        kg = await lightrag_knowledge_graph(self._rag, max_nodes=max_nodes)
        with session_factory() as session:
            gazetteer = build_gazetteer(session)
            proposals, notes = proposals_from_lightrag(
                kg, gazetteer, workspace=self.config.workspace, model=self.config.llm_model
            )
            stored = store_proposals(session, proposals, extractor="sion-lightrag-extractor/v1")
        return {"canonical": False, "proposals": len(proposals), "notes": notes, **stored}

    async def query(self, question: str, *, mode: str = "mix", top_k: int = 20) -> dict[str, Any]:
        """Answer with the LLM when configured; otherwise return retrieved context only.

        Without an LLM, graph modes cannot extract keywords from the question,
        so the question itself is used as the low-level keyword.
        """
        from lightrag import QueryParam

        if mode not in QUERY_MODES:
            raise ValueError(f"mode must be one of {sorted(QUERY_MODES)}")
        await self.start()
        if self.config.answers_enabled or self._llm_func is not None:
            with self._query_role():
                answer = await self._rag.aquery(question, param=QueryParam(mode=mode, top_k=top_k, enable_rerank=False))
            return {"mode": mode, "answer": answer}
        param = QueryParam(
            mode=mode,
            top_k=top_k,
            only_need_context=True,
            ll_keywords=[question],
            hl_keywords=[question],
            enable_rerank=False,
        )
        with self._query_role():
            context = await self._rag.aquery(question, param=param)
        return {"mode": mode, "context": context}
