#!/usr/bin/env python3
"""Local OpenAI-compatible embeddings endpoint for the GraphRAG layer (no cloud, no API key).

Serves ``POST /v1/embeddings`` with a multilingual ONNX model through ``fastembed`` so that
``SION_GRAPHRAG_EMBED_*`` can point at this machine::

    pip install fastembed            # once; the model (~220 MB) downloads on first start
    python scripts/local_embeddings.py --port 8765
    # SION_GRAPHRAG_EMBED_BASE_URL=http://127.0.0.1:8765/v1
    # SION_GRAPHRAG_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    # SION_GRAPHRAG_EMBED_DIM=384  SION_GRAPHRAG_EMBED_API_KEY=local  (any non-empty value)

Binds to 127.0.0.1 only. Answers both ``encoding_format`` ``float`` and ``base64``.
"""

from __future__ import annotations

import argparse
import base64
import os
from typing import Any

from pydantic import BaseModel

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str | None = "float"
    dimensions: int | None = None


def create_app(model_name: str = DEFAULT_MODEL, *, cache_dir: str | None = None, embedder: Any = None):
    import numpy as np
    from fastapi import FastAPI, HTTPException

    if embedder is None:
        from fastembed import TextEmbedding

        embedder = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    app = FastAPI(title="Sion local embeddings")

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": model_name, "object": "model"}]}

    @app.post("/v1/embeddings")
    def embeddings(request: EmbeddingRequest):
        texts = [request.input] if isinstance(request.input, str) else list(request.input)
        if not texts:
            raise HTTPException(status_code=422, detail="input is empty")
        vectors = [np.asarray(v, dtype=np.float32) for v in embedder.embed(texts)]
        if request.dimensions is not None and vectors and request.dimensions != vectors[0].shape[0]:
            raise HTTPException(status_code=422, detail=f"model dimension is {vectors[0].shape[0]}")
        as_base64 = request.encoding_format == "base64"
        data = [
            {
                "object": "embedding",
                "index": i,
                "embedding": base64.b64encode(v.tobytes()).decode() if as_base64 else v.tolist(),
            }
            for i, v in enumerate(vectors)
        ]
        tokens = sum(len(t.split()) for t in texts)
        return {
            "object": "list",
            "data": data,
            "model": model_name,
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    return app


def main() -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=os.getenv("SION_LOCAL_EMBED_MODEL", DEFAULT_MODEL))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache-dir", default=os.getenv("SION_LOCAL_EMBED_CACHE"))
    args = parser.parse_args()
    uvicorn.run(create_app(args.model, cache_dir=args.cache_dir), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
