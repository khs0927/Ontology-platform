from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .schemas import EmbeddingCreate, VectorSearchRequest


class VectorBackendUnavailable(RuntimeError):
    pass


class VectorReferenceError(ValueError):
    pass


class VectorConflictError(ValueError):
    pass


def _require_pgvector(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise VectorBackendUnavailable(
            "vector operations require PostgreSQL with the pgvector extension"
        )
    installed = session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
    ).scalar_one()
    if not installed:
        raise VectorBackendUnavailable("pgvector extension is not enabled")


def _target_exists(session: Session, payload: EmbeddingCreate) -> None:
    if payload.entity_id is not None:
        exists = session.execute(
            text("SELECT EXISTS (SELECT 1 FROM entities WHERE id=:id)"),
            {"id": payload.entity_id},
        ).scalar_one()
        if not exists:
            raise VectorReferenceError("embedding entity does not exist")
        return

    exists = session.execute(
        text("SELECT EXISTS (SELECT 1 FROM chunks WHERE id=:id)"),
        {"id": payload.chunk_id},
    ).scalar_one()
    if not exists:
        raise VectorReferenceError("embedding chunk does not exist")


def create_embedding(session: Session, payload: EmbeddingCreate) -> dict:
    _require_pgvector(session)
    _target_exists(session, payload)

    vector_literal = json.dumps(payload.embedding, separators=(",", ":"))
    properties_json = json.dumps(payload.properties, ensure_ascii=False)

    try:
        row = session.execute(
            text(
                """
                INSERT INTO embeddings (
                    entity_id, chunk_id, model, dimensions, embedding,
                    content_hash, properties
                )
                VALUES (
                    :entity_id, :chunk_id, :model, :dimensions,
                    CAST(:embedding AS vector), :content_hash,
                    CAST(:properties AS jsonb)
                )
                RETURNING
                    id, entity_id, chunk_id, model, dimensions,
                    content_hash, properties, created_at
                """
            ),
            {
                "entity_id": payload.entity_id,
                "chunk_id": payload.chunk_id,
                "model": payload.model,
                "dimensions": len(payload.embedding),
                "embedding": vector_literal,
                "content_hash": payload.content_hash,
                "properties": properties_json,
            },
        ).mappings().one()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise VectorConflictError(
            "embedding already exists for this target/model/content hash"
        ) from exc

    return dict(row)


def search_vectors(session: Session, payload: VectorSearchRequest) -> list[dict]:
    _require_pgvector(session)

    vector_literal = json.dumps(payload.embedding, separators=(",", ":"))
    target_clause = ""
    if payload.target_kind == "entity":
        target_clause = "AND entity_id IS NOT NULL"
    elif payload.target_kind == "chunk":
        target_clause = "AND chunk_id IS NOT NULL"

    rows = session.execute(
        text(
            f"""
            SELECT
                id,
                entity_id,
                chunk_id,
                model,
                dimensions,
                1.0 - (embedding <=> CAST(:embedding AS vector)) AS similarity,
                content_hash,
                properties,
                created_at
            FROM embeddings
            WHERE model = :model
              AND dimensions = :dimensions
              {target_clause}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": vector_literal,
            "model": payload.model,
            "dimensions": len(payload.embedding),
            "limit": payload.limit,
        },
    ).mappings().all()

    return [dict(row) for row in rows]
