-- Optional Apache AGE projection. Safe to skip when the extension is absent.
-- Canonical truth remains public.entities / public.relations.

CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('sion_graph');
