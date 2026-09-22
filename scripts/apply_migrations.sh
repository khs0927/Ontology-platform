#!/usr/bin/env sh
set -eu

if [ -z "${ONTOLOGY_PG_DSN:-}" ]; then
  echo "ONTOLOGY_PG_DSN is required (standard postgresql:// DSN)." >&2
  exit 2
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required." >&2
  exit 2
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

for migration in "$ROOT_DIR"/migrations/[0-9][0-9][0-9]_*.sql; do
  [ -f "$migration" ] || continue
  echo "==> applying $(basename "$migration")"
  psql "$ONTOLOGY_PG_DSN" -X -v ON_ERROR_STOP=1 -f "$migration"
done

echo "All SQL migrations applied."
