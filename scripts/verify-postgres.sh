#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_MAJOR="${PG_MAJOR:-16}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/${PG_MAJOR}/bin}"
PGDATA="${PGDATA:-/tmp/sion-pg-verify}"
PGSOCK="${PGSOCK:-/tmp/sion-pg-sock}"
PGPORT="${PGPORT:-55432}"
DB="${SION_TEST_DB:-sion}"

for cmd in initdb pg_ctl createdb psql; do
  if [[ ! -x "$PG_BIN/$cmd" ]]; then
    echo "[ERROR] missing $PG_BIN/$cmd" >&2
    exit 2
  fi
done

rm -rf "$PGDATA" "$PGSOCK"
mkdir -p "$PGDATA" "$PGSOCK"
chown -R postgres:postgres "$PGDATA" "$PGSOCK"

cleanup() {
  runuser -u postgres -- "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
  rm -rf "$PGDATA" "$PGSOCK"
}
trap cleanup EXIT

runuser -u postgres -- "$PG_BIN/initdb"   -D "$PGDATA" -A trust --no-instructions >/dev/null

runuser -u postgres -- "$PG_BIN/pg_ctl"   -D "$PGDATA"   -l /tmp/sion-postgres-verify.log   -o "-F -p $PGPORT -k $PGSOCK -h 127.0.0.1" start >/dev/null

"$PG_BIN/createdb" -h "$PGSOCK" -p "$PGPORT" -U postgres "$DB"

for migration in   "$ROOT/migrations/001_core.sql"   "$ROOT/migrations/004_seed_core_types.sql"; do
  "$PG_BIN/psql" -v ON_ERROR_STOP=1     -h "$PGSOCK" -p "$PGPORT" -U postgres -d "$DB"     -f "$migration" >/dev/null
done

result="$("$PG_BIN/psql" -At   -h "$PGSOCK" -p "$PGPORT" -U postgres -d "$DB" -c "
SELECT count(*) FROM information_schema.tables WHERE table_schema='public';
SELECT count(*) FROM entity_types;
SELECT count(*) FROM relation_types;
SELECT extversion FROM pg_extension WHERE extname='pgcrypto';
")"

mapfile -t lines <<<"$result"
[[ "${lines[0]}" == "9" ]]
[[ "${lines[1]}" == "11" ]]
[[ "${lines[2]}" == "14" ]]
[[ -n "${lines[3]}" ]]

echo "[PASS] PostgreSQL core migrations"
echo "       tables=9 entity_types=11 relation_types=14 pgcrypto=${lines[3]}"
