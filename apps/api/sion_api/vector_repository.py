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


def require_pgvector(session: Session) -> None:
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


# Entities inside :project_ids (the Project entity itself or ``properties.project_id``); the
# same membership rule as repository.in_projects, written in SQL for the raw pgvector query.
_SCOPED_ENTITIES = """
    SELECT e.id FROM entities e
    WHERE e.id::text = ANY(CAST(:project_ids AS text[]))
       OR e.properties ->> 'project_id' = ANY(CAST(:project_ids AS text[]))
"""


def target_in_projects(session: Session, payload: EmbeddingCreate, projects: frozenset[str]) -> bool:
    """Whether the embedding's entity, or the entity behind its chunk's document, is in ``projects``."""
    if payload.entity_id is not None:
        statement = f"SELECT EXISTS (SELECT 1 FROM ({_SCOPED_ENTITIES}) s WHERE s.id = :id)"
        target = payload.entity_id
    else:
        statement = f"""
            SELECT EXISTS (
                SELECT 1 FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = :id AND d.entity_id IN ({_SCOPED_ENTITIES})
            )
        """
        target = payload.chunk_id
    return bool(
        session.execute(text(statement), {"id": target, "project_ids": sorted(projects)}).scalar_one()
    )


def create_embedding(session: Session, payload: EmbeddingCreate) -> dict:
    require_pgvector(session)
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


def search_vectors(
    session: Session, payload: VectorSearchRequest, projects: frozenset[str] | None = None
) -> list[dict]:
    """Nearest embeddings. With ``projects`` only embeddings of entities in those projects, or of
    chunks whose document entity is in them, are searched (``None`` is unrestricted)."""
    require_pgvector(session)

    vector_literal = json.dumps(payload.embedding, separators=(",", ":"))
    target_clause = ""
    if payload.target_kind == "entity":
        target_clause = "AND entity_id IS NOT NULL"
    elif payload.target_kind == "chunk":
        target_clause = "AND chunk_id IS NOT NULL"
    scope_clause = ""
    params: dict = {}
    if projects is not None:
        scope_clause = f"""
              AND (
                entity_id IN ({_SCOPED_ENTITIES})
                OR chunk_id IN (
                  SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
                  WHERE d.entity_id IN ({_SCOPED_ENTITIES})
                )
              )"""
        params["project_ids"] = sorted(projects)

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
              {target_clause}{scope_clause}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": vector_literal,
            "model": payload.model,
            "dimensions": len(payload.embedding),
            "limit": payload.limit,
            **params,
        },
    ).mappings().all()

    return [dict(row) for row in rows]
