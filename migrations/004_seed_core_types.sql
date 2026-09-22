BEGIN;

INSERT INTO entity_types (id, label, properties) VALUES
    ('Project', 'Project', '{}'::jsonb),
    ('Tool', 'Tool', '{}'::jsonb),
    ('Concept', 'Concept', '{}'::jsonb),
    ('Document', 'Document', '{}'::jsonb),
    ('Artifact', 'Artifact', '{}'::jsonb),
    ('Dataset', 'Dataset', '{}'::jsonb),
    ('SystemComponent', 'System Component', '{}'::jsonb),
    ('Workflow', 'Workflow', '{}'::jsonb),
    ('Decision', 'Decision', '{}'::jsonb),
    ('Deliverable', 'Deliverable', '{}'::jsonb)
ON CONFLICT (id) DO UPDATE SET
    label = EXCLUDED.label;

INSERT INTO relation_types (id, label, properties) VALUES
    ('RELATED_TO', 'Related To', '{}'::jsonb),
    ('USES', 'Uses', '{}'::jsonb),
    ('PRODUCES', 'Produces', '{}'::jsonb),
    ('DERIVED_FROM', 'Derived From', '{}'::jsonb),
    ('PART_OF', 'Part Of', '{}'::jsonb),
    ('DEPENDS_ON', 'Depends On', '{}'::jsonb),
    ('VALIDATES', 'Validates', '{}'::jsonb),
    ('REFERENCES', 'References', '{}'::jsonb),
    ('IMPLEMENTS', 'Implements', '{}'::jsonb),
    ('SUPPORTS', 'Supports', '{}'::jsonb)
ON CONFLICT (id) DO UPDATE SET
    label = EXCLUDED.label;

COMMIT;
