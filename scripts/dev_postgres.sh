#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || {
  echo "docker is required." >&2
  exit 2
}

ACTION=${1:-up}
PG_PORT=${ONTOLOGY_PG_PORT:-5433}

wait_for_postgres() {
  echo "Waiting for PostgreSQL..."
  i=0
  until docker compose exec -T postgres pg_isready -U ontology -d ontology_platform >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 40 ]; then
      echo "PostgreSQL did not become ready." >&2
      exit 1
    fi
    sleep 1
  done
}

apply_migrations_in_container() {
  for migration in migrations/[0-9][0-9][0-9]_*.sql; do
    [ -f "$migration" ] || continue
    echo "==> applying $(basename "$migration")"
    docker compose exec -T postgres       psql -U ontology -d ontology_platform -X -v ON_ERROR_STOP=1 < "$migration"
  done
}

case "$ACTION" in
  up)
    docker compose up -d postgres
    wait_for_postgres
    apply_migrations_in_container
    export ONTOLOGY_DATABASE_URL="postgresql+psycopg://ontology@127.0.0.1:${PG_PORT}/ontology_platform"
    python scripts/verify_postgres.py
    echo
    echo "PostgreSQL runtime ready on 127.0.0.1:${PG_PORT}"
    echo "ONTOLOGY_DATABASE_URL=$ONTOLOGY_DATABASE_URL"
    ;;
  verify)
    wait_for_postgres
    export ONTOLOGY_DATABASE_URL="postgresql+psycopg://ontology@127.0.0.1:${PG_PORT}/ontology_platform"
    python scripts/verify_postgres.py
    ;;
  down)
    docker compose down
    ;;
  reset)
    echo "This removes the local development PostgreSQL volume."
    docker compose down -v
    ;;
  *)
    echo "Usage: $0 [up|verify|down|reset]" >&2
    exit 2
    ;;
esac
