#!/usr/bin/env bash
set -euo pipefail

PG_MAJOR="${PG_MAJOR:-16}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-0.8.6}"
PREFIX_CONTROL="/usr/share/postgresql/${PG_MAJOR}/extension/vector.control"

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] run as root (or through sudo)" >&2
  exit 2
fi

if [[ -f "$PREFIX_CONTROL" ]] && grep -q "default_version = '$PGVECTOR_VERSION'" "$PREFIX_CONTROL"; then
  echo "[OK] pgvector $PGVECTOR_VERSION already installed for PostgreSQL $PG_MAJOR"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq   build-essential   git   "postgresql-server-dev-${PG_MAJOR}"

src="/tmp/sion-pgvector-${PGVECTOR_VERSION}"
rm -rf "$src"
git clone --quiet --depth 1   --branch "v${PGVECTOR_VERSION}"   https://github.com/pgvector/pgvector.git "$src"

make -s -C "$src"
make -s -C "$src" install

actual="$(sed -n "s/^default_version = '\([^']*\)'.*/\1/p" "$PREFIX_CONTROL")"
[[ "$actual" == "$PGVECTOR_VERSION" ]]

echo "[PASS] pgvector $actual installed for PostgreSQL $PG_MAJOR"
