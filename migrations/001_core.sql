BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ontology_versions (
    version TEXT PRIMARY KEY,
    schema_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS entity_types (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    parent_type_id TEXT REFERENCES entity_types(id),
    schema_uri TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS relation_types (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    inverse_type_id TEXT REFERENCES relation_types(id),
    source_type_id TEXT REFERENCES entity_types(id),
    target_type_id TEXT REFERENCES entity_types(id),
    transitive BOOLEAN NOT NULL DEFAULT FALSE,
    is_symmetric BOOLEAN NOT NULL DEFAULT FALSE,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stable_key TEXT NOT NULL UNIQUE,
    entity_type_id TEXT NOT NULL REFERENCES entity_types(id),
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    external_uri TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    ontology_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stable_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    content_hash TEXT,
    mime_type TEXT,
    byte_size BIGINT CHECK (byte_size IS NULL OR byte_size >= 0),
    provider TEXT,
    provider_file_id TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID UNIQUE REFERENCES entities(id) ON DELETE CASCADE,
    artifact_id UUID REFERENCES artifacts(id),
    language TEXT,
    title TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content TEXT NOT NULL,
    content_hash TEXT,
    locator TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stable_key TEXT NOT NULL UNIQUE,
    source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type_id TEXT NOT NULL REFERENCES relation_types(id),
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_state IN ('unverified','machine_verified','human_verified','rejected')),
    source_kind TEXT,
    ontology_version TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_entity_id <> target_entity_id OR relation_type_id = 'RELATED_TO')
);

CREATE TABLE IF NOT EXISTS evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,
    relation_id UUID REFERENCES relations(id) ON DELETE CASCADE,
    artifact_id UUID REFERENCES artifacts(id),
    chunk_id UUID REFERENCES chunks(id),
    source_uri TEXT,
    source_locator TEXT,
    excerpt_hash TEXT,
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_state IN ('unverified','machine_verified','human_verified','rejected')),
    extractor TEXT,
    model TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (entity_id IS NOT NULL OR relation_id IS NOT NULL),
    CHECK (artifact_id IS NOT NULL OR chunk_id IS NOT NULL OR source_uri IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type_id);
CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category);
CREATE INDEX IF NOT EXISTS idx_entities_properties_gin ON entities USING GIN(properties);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(relation_type_id);
CREATE INDEX IF NOT EXISTS idx_relations_properties_gin ON relations USING GIN(properties);
CREATE INDEX IF NOT EXISTS idx_evidence_relation ON evidence(relation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_entity ON evidence(entity_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

COMMIT;
