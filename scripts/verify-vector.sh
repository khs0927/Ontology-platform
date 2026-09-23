#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_MAJOR="${PG_MAJOR:-16}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/${PG_MAJOR}/bin}"
PGDATA="${PGDATA:-/tmp/sion-pgvector-verify}"
PGSOCK="${PGSOCK:-/tmp/sion-pgvector-sock}"
PGPORT="${PGPORT:-55433}"
DB="${SION_TEST_DB:-sion_vector}"

if [[ ! -f "/usr/share/postgresql/${PG_MAJOR}/extension/vector.control" ]]; then
  echo "[ERROR] pgvector is not installed for PostgreSQL $PG_MAJOR" >&2
  exit 3
fi

rm -rf "$PGDATA" "$PGSOCK"
mkdir -p "$PGDATA" "$PGSOCK"
chown -R postgres:postgres "$PGDATA" "$PGSOCK"

cleanup() {
  runuser -u postgres -- "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
  rm -rf "$PGDATA" "$PGSOCK"
}
trap cleanup EXIT

runuser -u postgres -- "$PG_BIN/initdb"   -D "$PGDATA" -A trust --no-instructions >/dev/null
runuser -u postgres -- "$PG_BIN/pg_ctl"   -D "$PGDATA"   -l /tmp/sion-pgvector-verify.log   -o "-F -p $PGPORT -k $PGSOCK -h 127.0.0.1" start >/dev/null

"$PG_BIN/createdb" -h "$PGSOCK" -p "$PGPORT" -U postgres "$DB"

for migration in   "$ROOT/migrations/001_core.sql"   "$ROOT/migrations/004_seed_core_types.sql"   "$ROOT/migrations/002_vector.sql"; do
  "$PG_BIN/psql" -v ON_ERROR_STOP=1     -h "$PGSOCK" -p "$PGPORT" -U postgres -d "$DB"     -f "$migration" >/dev/null
done

"$PG_BIN/psql" -v ON_ERROR_STOP=1 -qAt   -h "$PGSOCK" -p "$PGPORT" -U postgres -d "$DB" <<'SQL' >/tmp/sion-vector-check.txt
INSERT INTO entities (stable_key, entity_type_id, name, category)
VALUES
  ('vector:test:a', 'Concept', 'Vector A', 'data_validation'),
  ('vector:test:b', 'Concept', 'Vector B', 'data_validation');

INSERT INTO embeddings (entity_id, model, dimensions, embedding, content_hash)
SELECT id, 'test/free-model', 3,
       CASE stable_key
         WHEN 'vector:test:a' THEN '[1,0,0]'::vector
         ELSE '[0.8,0.2,0]'::vector
       END,
       'sha256:' || repeat(CASE stable_key
         WHEN 'vector:test:a' THEN 'a'
         ELSE 'b'
       END, 64)
FROM entities
WHERE stable_key IN ('vector:test:a', 'vector:test:b');

SELECT extversion FROM pg_extension WHERE extname='vector';
SELECT count(*) FROM embeddings;
SELECT dimensions FROM embeddings ORDER BY created_at LIMIT 1;
SELECT e.stable_key
FROM embeddings v
JOIN entities e ON e.id=v.entity_id
ORDER BY v.embedding <=> '[1,0,0]'::vector
LIMIT 1;
SQL

mapfile -t lines </tmp/sion-vector-check.txt
[[ "${lines[0]}" == "0.8.6" ]]
[[ "${lines[1]}" == "2" ]]
[[ "${lines[2]}" == "3" ]]
[[ "${lines[3]}" == "vector:test:a" ]]

echo "[PASS] pgvector native storage and cosine search"
echo "       vector=${lines[0]} rows=${lines[1]} dims=${lines[2]} nearest=${lines[3]}"
