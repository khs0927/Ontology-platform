"""LightRAG adapter: expose an ``Embedder`` as the async ``embedding_func`` LightRAG expects.

LightRAG hands the function bare texts, but asymmetric models (nemotron, nv-vl) need to know whether a
text is a stored passage or a search query. Indexing is the default (``passage``); wrap retrieval in
``as_query()`` so the same function embeds queries with ``input_type="query"``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .providers import Embedder

_ROLE: ContextVar[str] = ContextVar("sion_embedhub_role", default="passage")


@contextmanager
def as_query() -> Iterator[None]:
    """Embed with role='query' for everything awaited inside this block."""
    token = _ROLE.set("query")
    try:
        yield
    finally:
        _ROLE.reset(token)


def lightrag_embedding_func(embedder: Embedder, dim: int | None = None) -> Callable[[list[str]], Awaitable[object]]:
    """Async ``texts -> numpy array`` (rows L2-normalised, ``dim`` columns). The blocking HTTP runs in a thread."""

    async def embed(texts: list[str]):
        import numpy as np

        role = _ROLE.get()  # read before the thread hop; the thread gets a copy of the context anyway
        vectors = await asyncio.to_thread(embedder.embed, list(texts), role, dim)
        return np.array(vectors, dtype=np.float32)

    return embed
