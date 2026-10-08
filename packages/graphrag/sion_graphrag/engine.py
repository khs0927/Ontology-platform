"""LightRAG engine wrapper: PostgreSQL storage, OpenAI-compatible model endpoints.

LightRAG is an optional dependency (``pip install -e .[graphrag]``). It is only
imported when an engine is started, because importing it can install missing
provider packages at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session, sessionmaker

from .projection import build_custom_kg

PROJECT_ROOT = Path(__file__).resolve().parents[3]

POSTGRES_STORAGES = {
    "kv_storage": "PGKVStorage",
    "vector_storage": "PGVectorStorage",
    "graph_storage": "PGGraphStorage",
    "doc_status_storage": "PGDocStatusStorage",
}
LOCAL_STORAGES = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": "NetworkXStorage",
    "doc_status_storage": "JsonDocStatusStorage",
}
QUERY_MODES = {"local", "global", "hybrid", "naive", "mix"}


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

    @classmethod
    def from_env(cls) -> "GraphRagConfig | None":
        model = os.getenv("SION_GRAPHRAG_EMBED_MODEL")
        dim = os.getenv("SION_GRAPHRAG_EMBED_DIM")
        if not model or not dim:
            return None
        storage = os.getenv("SION_GRAPHRAG_STORAGE", "postgres").strip().lower()
        if storage not in {"postgres", "local"}:
            raise ValueError("SION_GRAPHRAG_STORAGE must be 'postgres' or 'local'")
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
        )

    @property
    def answers_enabled(self) -> bool:
        return bool(self.llm_model)


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

    def _build(self):
        try:
            from lightrag import LightRAG
            from lightrag.utils import EmbeddingFunc
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise GraphRagUnavailable("install the 'rag' extra: pip install 'sion-ontology-platform[rag]' (lightrag-hku)") from exc
        config = self.config
        embed = self._embedding_func
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

        storages = POSTGRES_STORAGES if config.storage == "postgres" else LOCAL_STORAGES
        config.working_dir.mkdir(parents=True, exist_ok=True)
        extra: dict[str, Any] = {"tokenizer": self._tokenizer} if self._tokenizer is not None else {}
        return LightRAG(
            working_dir=str(config.working_dir),
            workspace=config.workspace,
            embedding_func=EmbeddingFunc(
                embedding_dim=config.embedding_dim,
                func=embed,
                model_name=config.embedding_model,
            ),
            llm_model_func=llm or _no_llm,
            **storages,
            **extra,
        )

    async def start(self) -> None:
        if self._rag is None:
            rag = self._build()
            await rag.initialize_storages()
            self._rag = rag

    async def close(self) -> None:
        if self._rag is not None:
            await self._rag.finalize_storages()
            self._rag = None

    async def project(self, session_factory: sessionmaker[Session]) -> dict[str, int]:
        """Upsert the canonical graph into LightRAG and return what was written."""
        with session_factory() as session:
            custom_kg = build_custom_kg(session)
        await self.start()
        if custom_kg["chunks"]:
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
        context = await self._rag.aquery(question, param=param)
        return {"mode": mode, "context": context}
