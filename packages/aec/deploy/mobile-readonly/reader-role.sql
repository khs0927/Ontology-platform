-- Read-only login for a restored copy of database "aec".
-- Run as the database owner, connected to that database, on the copy only.
-- Do not run this against the live PC database.
-- This file has no password. After it succeeds, set one in the local session:
--   \password aec_reader
-- Never commit that password.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aec_reader') THEN
    CREATE ROLE aec_reader LOGIN;
  END IF;
END
$$;

ALTER ROLE aec_reader SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE aec TO aec_reader;
GRANT USAGE ON SCHEMA aec, ag_catalog, public TO aec_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA aec TO aec_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog TO aec_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aec_reader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ag_catalog TO aec_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA aec GRANT SELECT ON TABLES TO aec_reader;

-- The API refuses to log in as the owner. Confirm the reader cannot write.
-- Both counts must be 0 before the mobile API is pointed here:
--   SELECT count(*) FROM information_schema.role_table_grants
--    WHERE grantee = 'aec_reader'
--      AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES');
-- If cypher() is SECURITY DEFINER (pg_proc.prosecdef), revoke EXECUTE and skip graph
-- expansion instead of granting a definer function that writes as the owner.
