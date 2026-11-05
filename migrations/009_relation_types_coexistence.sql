-- 009: add the Hueflow/mcp2 coexistence relation types (16th-22nd core relation types).
-- Needed by data/bootstrap/hueflow-mcp2-coexistence-20261027.json (sion-map-export/v1),
-- whose edges use BLOCKS, COEXISTS_WITH, DOCUMENTS, FALLBACK_FOR, MUST_NOT,
-- PREFERRED_FOR and USES_PORT. Mirrors sion_api.repository.seed_core_types and
-- sion_ingestion.graph_export.KNOWN_RELATION_TYPES.
-- Additive and idempotent; never updates or deletes existing rows.
BEGIN;

INSERT INTO relation_types (
  id, label, inverse_type_id, source_type_id, target_type_id,
  transitive, is_symmetric, properties
) VALUES
  ('BLOCKS', 'Blocks', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('COEXISTS_WITH', 'Coexists With', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('DOCUMENTS', 'Documents', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('FALLBACK_FOR', 'Fallback For', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('MUST_NOT', 'Must Not', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('PREFERRED_FOR', 'Preferred For', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('USES_PORT', 'Uses Port', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

COMMIT;
