-- Optional Apache AGE projection. Safe to skip when the extension is absent.
-- Canonical truth remains public.entities / public.relations.
-- Idempotent: replaying this file does not fail when the graph already exists.

CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'sion_graph') THEN
    PERFORM ag_catalog.create_graph('sion_graph');
  END IF;
END $$;
