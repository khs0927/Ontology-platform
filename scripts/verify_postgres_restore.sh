#!/usr/bin/env bash
set -Eeuo pipefail

: "${ONTOLOGY_PG_DSN:?ONTOLOGY_PG_DSN must point to the disposable source CI database}"
: "${ONTOLOGY_RESTORE_PG_DSN:?ONTOLOGY_RESTORE_PG_DSN must point to the fresh restore CI database}"
: "${ONTOLOGY_RESTORE_DATABASE_URL:?ONTOLOGY_RESTORE_DATABASE_URL is required}"
: "${ONTOLOGY_TEST_POSTGRES_URL:?ONTOLOGY_TEST_POSTGRES_URL is required}"

archive="$(mktemp "${TMPDIR:-/tmp}/ontology-platform-restore.XXXXXX.dump")"
trap 'rm -f "$archive"' EXIT

pg_dump --format=custom --file="$archive" "$ONTOLOGY_PG_DSN"
test -s "$archive"

psql "$ONTOLOGY_PG_DSN" -X -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS ontology_restore_test; CREATE DATABASE ontology_restore_test;'
psql "$ONTOLOGY_RESTORE_PG_DSN" -X -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS public CASCADE;'
pg_restore --exit-on-error --no-owner --no-acl --dbname="$ONTOLOGY_RESTORE_PG_DSN" "$archive"

for table in ontology_versions entity_types relation_types entities artifacts documents chunks relations evidence embeddings; do
  source_count="$(psql "$ONTOLOGY_PG_DSN" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.\"$table\"")"
  restored_count="$(psql "$ONTOLOGY_RESTORE_PG_DSN" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.\"$table\"")"
  if [[ "$source_count" != "$restored_count" ]]; then
    printf 'Restore row-count mismatch for %s: source=%s restored=%s\n' "$table" "$source_count" "$restored_count" >&2
    exit 1
  fi
done

ONTOLOGY_PG_DSN="$ONTOLOGY_RESTORE_PG_DSN" \
ONTOLOGY_DATABASE_URL="$ONTOLOGY_RESTORE_DATABASE_URL" \
uv run python scripts/verify_postgres.py

ONTOLOGY_TEST_POSTGRES_URL="$ONTOLOGY_RESTORE_DATABASE_URL" \
uv run pytest -q tests/test_postgres_integration.py
