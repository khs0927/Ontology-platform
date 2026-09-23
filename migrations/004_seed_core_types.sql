BEGIN;

INSERT INTO entity_types (id, label, parent_type_id, schema_uri, properties) VALUES
  ('Entity', 'Entity', NULL, NULL, '{}'::jsonb),
  ('Project', 'Project', 'Entity', NULL, '{}'::jsonb),
  ('Tool', 'Tool', 'Entity', NULL, '{}'::jsonb),
  ('Concept', 'Concept', 'Entity', NULL, '{}'::jsonb),
  ('Document', 'Document', 'Entity', NULL, '{}'::jsonb),
  ('Artifact', 'Artifact', 'Entity', NULL, '{}'::jsonb),
  ('Dataset', 'Dataset', 'Artifact', NULL, '{}'::jsonb),
  ('SystemComponent', 'System Component', 'Entity', NULL, '{}'::jsonb),
  ('Workflow', 'Workflow', 'Entity', NULL, '{}'::jsonb),
  ('Decision', 'Decision', 'Entity', NULL, '{}'::jsonb),
  ('Deliverable', 'Deliverable', 'Artifact', NULL, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO relation_types (
  id, label, inverse_type_id, source_type_id, target_type_id,
  transitive, is_symmetric, properties
) VALUES
  ('RELATED_TO', 'Related to', NULL, NULL, NULL, FALSE, TRUE, '{}'::jsonb),
  ('PART_OF', 'Part of', NULL, NULL, NULL, TRUE, FALSE, '{}'::jsonb),
  ('USES', 'Uses', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('PRODUCES', 'Produces', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('DERIVED_FROM', 'Derived from', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('REFERENCES', 'References', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('IMPLEMENTS', 'Implements', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('DEPENDS_ON', 'Depends on', NULL, NULL, NULL, TRUE, FALSE, '{}'::jsonb),
  ('CONNECTS_TO', 'Connects to', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('SUPPORTS', 'Supports', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('EXTRACTED_FROM', 'Extracted from', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('EVIDENCED_BY', 'Evidenced by', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('SUPERSEDES', 'Supersedes', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('VERSION_OF', 'Version of', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

COMMIT;
