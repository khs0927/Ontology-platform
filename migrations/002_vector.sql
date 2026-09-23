-- Native vector storage. Requires the free pgvector PostgreSQL extension.
--
-- The base embedding column intentionally has no fixed typmod so Sion can
-- support multiple free/local embedding models during evaluation.
-- Model-specific ANN indexes are added later as partial expression indexes
-- once a model + dimension contract is promoted to production.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id UUID REFERENCES chunks(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    embedding vector NOT NULL,
    content_hash TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- An embedding belongs to exactly one semantic target.
    CHECK (num_nonnulls(entity_id, chunk_id) = 1),

    -- Prevent caller metadata from lying about the actual vector shape.
    CHECK (vector_dims(embedding) = dimensions)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_entity
    ON embeddings(entity_id)
    WHERE entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk
    ON embeddings(chunk_id)
    WHERE chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_embeddings_model_dimensions
    ON embeddings(model, dimensions);

CREATE UNIQUE INDEX IF NOT EXISTS uq_embeddings_entity_model_hash
    ON embeddings(entity_id, model, content_hash)
    WHERE entity_id IS NOT NULL AND content_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_embeddings_chunk_model_hash
    ON embeddings(chunk_id, model, content_hash)
    WHERE chunk_id IS NOT NULL AND content_hash IS NOT NULL;

COMMIT;

-- Example model-specific ANN index, intentionally NOT executed:
--
-- CREATE INDEX embeddings_bge_m3_hnsw
--   ON embeddings
--   USING hnsw ((embedding::vector(1024)) vector_cosine_ops)
--   WHERE model = 'BAAI/bge-m3' AND dimensions = 1024;
