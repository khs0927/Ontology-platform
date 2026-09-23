BEGIN;

-- A removed Artifact or Chunk must not leave dangling Evidence. A Document
-- survives loss of its storage Artifact, so its optional pointer becomes NULL.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents'::regclass
          AND conname = 'documents_artifact_id_fkey'
          AND confdeltype <> 'n'
    ) THEN
        ALTER TABLE documents DROP CONSTRAINT documents_artifact_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents'::regclass
          AND conname = 'documents_artifact_id_fkey'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_artifact_id_fkey
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'evidence'::regclass
          AND conname = 'evidence_artifact_id_fkey'
          AND confdeltype <> 'c'
    ) THEN
        ALTER TABLE evidence DROP CONSTRAINT evidence_artifact_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'evidence'::regclass
          AND conname = 'evidence_artifact_id_fkey'
    ) THEN
        ALTER TABLE evidence ADD CONSTRAINT evidence_artifact_id_fkey
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'evidence'::regclass
          AND conname = 'evidence_chunk_id_fkey'
          AND confdeltype <> 'c'
    ) THEN
        ALTER TABLE evidence DROP CONSTRAINT evidence_chunk_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'evidence'::regclass
          AND conname = 'evidence_chunk_id_fkey'
    ) THEN
        ALTER TABLE evidence ADD CONSTRAINT evidence_chunk_id_fkey
            FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
