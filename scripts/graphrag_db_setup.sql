-- One-time setup of a dedicated LightRAG database on an existing PostgreSQL
-- server that already has the pgvector extension installed, such as the
-- Ontology pipeline's aec-postgres-age container. Run as a superuser:
--
--   psql -h localhost -p 55432 -U aec -d aec -f scripts/graphrag_db_setup.sql
--
-- The projection lives in its own database so it never mixes with the
-- canonical `aec` schema and can be dropped and rebuilt at any time.
--
-- The default graph backend (SION_GRAPHRAG_GRAPH_BACKEND=table) uses plain
-- tables and needs no Apache AGE. Only the legacy backend
-- (SION_GRAPHRAG_GRAPH_BACKEND=age) needs the commented lines below; see
-- docs/GRAPHRAG.md "Graph backend".

CREATE DATABASE sion_graphrag;

\connect sion_graphrag
CREATE EXTENSION IF NOT EXISTS vector;

-- Legacy AGE backend only:
-- ALTER DATABASE sion_graphrag SET session_preload_libraries = 'age';
-- CREATE EXTENSION IF NOT EXISTS age;
