#!/usr/bin/env bash
set -Eeuo pipefail

: "${ONTOLOGY_PG_DSN:?ONTOLOGY_PG_DSN must point to the disposable source CI database}"
: "${ONTOLOGY_RESTORE_PG_DSN:?ONTOLOGY_RESTORE_PG_DSN must point to the fresh restore CI database}"
: "${ONTOLOGY_RESTORE_DATABASE_URL:?ONTOLOGY_RESTORE_DATABASE_URL is required}"
: "${ONTOLOGY_TEST_POSTGRES_URL:?ONTOLOGY_TEST_POSTGRES_URL is required}"

echo "Starting PostgreSQL backup and restore verification..."
archive="$(mktemp "${TMPDIR:-/tmp}/ontology-platform-restore.XXXXXX.dump")"
trap 'rm -f "$archive"' EXIT

echo "Creating pg_dump archive..."
pg_dump --dbname="$ONTOLOGY_PG_DSN" --format=custom --file="$archive"
test -s "$archive"
echo "Archive created successfully: $(wc -c < "$archive") bytes"

echo "Recreating restore database..."
psql "$ONTOLOGY_PG_DSN" -X -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS ontology_restore_test'
psql "$ONTOLOGY_PG_DSN" -X -v ON_ERROR_STOP=1 -c 'CREATE DATABASE ontology_restore_test'

echo "Restoring archive into ontology_restore_test..."
pg_restore --clean --if-exists --no-owner --no-acl --dbname="$ONTOLOGY_RESTORE_PG_DSN" "$archive" || {
  rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "pg_restore failed with fatal exit code $rc" >&2
    exit "$rc"
  fi
  echo "pg_restore completed with ignorable warnings (code $rc)"
}

echo "Verifying table row counts between source and restored database..."
for table in ontology_versions entity_types relation_types entities artifacts documents chunks relations evidence embeddings; do
  source_count="$(psql "$ONTOLOGY_PG_DSN" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.\"$table\"")"
  restored_count="$(psql "$ONTOLOGY_RESTORE_PG_DSN" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.\"$table\"")"
  if [[ "$source_count" != "$restored_count" ]]; then
    printf 'Restore row-count mismatch for %s: source=%s restored=%s\n' "$table" "$source_count" "$restored_count" >&2
    exit 1
  fi
  printf '  Table %s: %s rows verified\n' "$table" "$restored_count"
done

echo "Verifying schema integrity on restored database..."
ONTOLOGY_PG_DSN="$ONTOLOGY_RESTORE_PG_DSN" \
ONTOLOGY_DATABASE_URL="$ONTOLOGY_RESTORE_DATABASE_URL" \
uv run python scripts/verify_postgres.py

echo "Rerunning integration tests against restored database..."
ONTOLOGY_TEST_POSTGRES_URL="$ONTOLOGY_RESTORE_DATABASE_URL" \
uv run pytest -q tests/test_postgres_integration.py

echo "PostgreSQL backup and restore verification passed!"
