BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_entities_category'
          AND conrelid = 'entities'::regclass
    ) THEN
        ALTER TABLE entities
            ADD CONSTRAINT ck_entities_category
            CHECK (
                category IS NULL OR category IN (
                    'core',
                    'architecture_site',
                    'cad_bim',
                    'ai_automation',
                    'content_assets',
                    'data_validation'
                )
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_relations_source_kind'
          AND conrelid = 'relations'::regclass
    ) THEN
        ALTER TABLE relations
            ADD CONSTRAINT ck_relations_source_kind
            CHECK (
                source_kind IS NULL OR source_kind IN (
                    'user',
                    'document',
                    'file',
                    'database',
                    'api',
                    'mcp',
                    'inferred',
                    'imported'
                )
            );
    END IF;
END
$$;

COMMIT;
