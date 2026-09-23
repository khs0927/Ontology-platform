BEGIN;

ALTER TABLE artifacts
    ADD COLUMN IF NOT EXISTS entity_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_artifacts_entity_id'
          AND conrelid = 'artifacts'::regclass
    ) THEN
        ALTER TABLE artifacts
            ADD CONSTRAINT fk_artifacts_entity_id
            FOREIGN KEY (entity_id)
            REFERENCES entities(id)
            ON DELETE CASCADE;
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_entity_id
    ON artifacts(entity_id)
    WHERE entity_id IS NOT NULL;

COMMIT;
