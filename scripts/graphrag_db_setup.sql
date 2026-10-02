-- One-time setup of a dedicated LightRAG database on an existing PostgreSQL
-- server that already has the AGE and pgvector extensions installed, such as
-- the Ontology pipeline's aec-postgres-age container. Run as a superuser:
--
--   psql -h localhost -p 55432 -U aec -d aec -f scripts/graphrag_db_setup.sql
--
-- The projection lives in its own database so it never mixes with the
-- canonical `aec` schema and can be dropped and rebuilt at any time.

CREATE DATABASE sion_graphrag;

-- LightRAG needs AGE loaded in every session. Loading it per database avoids
-- changing the server's shared_preload_libraries.
ALTER DATABASE sion_graphrag SET session_preload_libraries = 'age';

\connect sion_graphrag
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
