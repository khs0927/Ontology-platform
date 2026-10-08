-- 007: add the VALIDATES relation type (15th core relation type).
-- Needed by the Sion Map export (3 of its 43 edges are VALIDATES) and by the
-- candidate-relation extractor ("X validates Y" / "X는 Y를 검증").
-- Additive and idempotent; never updates or deletes existing rows.
BEGIN;

INSERT INTO relation_types (
  id, label, inverse_type_id, source_type_id, target_type_id,
  transitive, is_symmetric, properties
) VALUES
  ('VALIDATES', 'Validates', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

COMMIT;
