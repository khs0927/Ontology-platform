"""Unified PostgreSQL migration runner for the Sion monorepo.

One database, two schemas:

* ``public``      Sion core (``migrations/*.sql``): entities, relations, evidence,
                  artifacts, embeddings, outbox_events. Tracked in
                  ``public.sion_schema_migrations``.
* ``regulation``  ArchOntos (``packages/regulation/db/migrations``), applied by
                  ArchOntos' own runner (``archontos.db.migrate``) with
                  ``search_path = regulation, public``; tracked in
                  ``regulation.schema_migrations``.

Extensions (pgcrypto, vector) are installed once in ``public`` so both schemas
resolve them. Every file is applied once and checksummed (CRLF-normalised); an
edited, already-applied file is an error. The Sion SQL files are idempotent, so
a database created earlier by replaying them with psql is adopted safely.

Usage::

    python -m sion_api.migrate --dsn postgresql://...        # core + regulation
    python -m sion_api.migrate --status
    python -m sion_api.migrate --skip-regulation             # core only
    python -m sion_api.migrate --with-age                    # + optional Apache AGE projection
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT

CORE_DIR = PROJECT_ROOT / "migrations"
REGULATION_DIR = PROJECT_ROOT / "packages" / "regulation" / "db" / "migrations"
CORE_SEQUENCE = ("001_core", "002_vector", "004_seed_core_types", "006_outbox", "007_relation_type_validates")
OPTIONAL_AGE = "005_age_projection"
LOCK_KEY = 7_146_221_202  # distinct from ArchOntos' 7_146_221_101
_SELF_TRANSACTIONAL = re.compile(r"^\s*(--[^\n]*\n|\s)*BEGIN\s*;", re.IGNORECASE)
_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoreMigration:
    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8-sig")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def core_migrations(*, with_age: bool = False, directory: Path = CORE_DIR) -> list[CoreMigration]:
    versions = list(CORE_SEQUENCE)
    if with_age:
        versions.insert(versions.index("006_outbox"), OPTIONAL_AGE)
    found = []
    for version in versions:
        path = directory / f"{version}.sql"
        if not path.is_file():
            raise MigrationError(f"missing core migration {path}")
        found.append(CoreMigration(version, path))
    return found


def plain_dsn(dsn: str) -> str:
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql+psycopg2://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix):]
    return dsn


def apply_core(dsn: str, *, with_age: bool = False) -> list[str]:
    import psycopg

    applied_now: list[str] = []
    with psycopg.connect(plain_dsn(dsn), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            conn.execute("SET search_path TO public")
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS public.sion_schema_migrations (
                       version text PRIMARY KEY,
                       checksum text NOT NULL,
                       applied_at timestamptz NOT NULL DEFAULT now())"""
            )
            recorded = dict(conn.execute("SELECT version, checksum FROM public.sion_schema_migrations").fetchall())
            for migration in core_migrations(with_age=with_age):
                if migration.version in recorded:
                    if recorded[migration.version] != migration.checksum:
                        raise MigrationError(
                            f"{migration.version} was edited after it was applied (checksum mismatch); "
                            "add a new migration instead"
                        )
                    continue
                sql = migration.sql
                if _SELF_TRANSACTIONAL.match(sql):
                    try:
                        conn.execute(sql)
                    except BaseException:
                        conn.execute("ROLLBACK")
                        raise
                    conn.execute(
                        "INSERT INTO public.sion_schema_migrations(version, checksum) VALUES (%s, %s)",
                        (migration.version, migration.checksum),
                    )
                else:
                    with conn.transaction():
                        conn.execute(sql)
                        conn.execute(
                            "INSERT INTO public.sion_schema_migrations(version, checksum) VALUES (%s, %s)",
                            (migration.version, migration.checksum),
                        )
                applied_now.append(migration.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


async def _apply_regulation(dsn: str, schema: str) -> list[str]:
    import asyncpg
    from archontos.db.migrate import apply_migrations, use_schema

    conn = await asyncpg.connect(plain_dsn(dsn), timeout=30)
    try:
        await use_schema(conn, schema)
        return await apply_migrations(conn, REGULATION_DIR)
    finally:
        await conn.close()


def apply_regulation(dsn: str, *, schema: str = "regulation") -> list[str]:
    if not _SCHEMA.match(schema) or schema == "public":
        raise MigrationError(f"regulation schema must be a plain identifier other than public, got {schema!r}")
    try:
        import asyncpg  # noqa: F401
        from archontos.db import migrate as _ao  # noqa: F401
    except ImportError as exc:
        raise MigrationError(
            "ArchOntos migrations need the 'regulation' extra: pip install 'sion-ontology-platform[regulation]'"
        ) from exc
    return asyncio.run(_apply_regulation(dsn, schema))


def status(dsn: str, *, schema: str = "regulation", with_age: bool = False) -> dict:
    import psycopg

    with psycopg.connect(plain_dsn(dsn), autocommit=True) as conn:
        has_core = conn.execute("SELECT to_regclass('public.sion_schema_migrations') IS NOT NULL").fetchone()[0]
        recorded = dict(conn.execute("SELECT version, checksum FROM public.sion_schema_migrations").fetchall()) if has_core else {}
        core = core_migrations(with_age=with_age)
        reg_table = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.schema_migrations",)).fetchone()[0]
        reg_applied = (
            [row[0] for row in conn.execute(f'SELECT version FROM "{schema}".schema_migrations ORDER BY version').fetchall()]
            if reg_table and _SCHEMA.match(schema)
            else []
        )
    reg_all = sorted(p.stem for p in REGULATION_DIR.glob("*.sql"))
    return {
        "core": {
            "applied": [m.version for m in core if m.version in recorded],
            "pending": [m.version for m in core if m.version not in recorded],
            "edited": [m.version for m in core if m.version in recorded and recorded[m.version] != m.checksum],
        },
        "regulation": {
            "schema": schema,
            "applied": reg_applied,
            "pending": [v for v in reg_all if v not in reg_applied],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sion_api.migrate", description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=None, help="default: SION_DATABASE_URL")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--with-age", action="store_true", help="also apply 005_age_projection (needs Apache AGE)")
    parser.add_argument("--skip-regulation", action="store_true", help="only the Sion core schema")
    parser.add_argument("--regulation-schema", default=os.getenv("ARCHONTOS_DB_SCHEMA") or "regulation")
    args = parser.parse_args(argv)
    dsn = args.dsn or os.getenv("SION_DATABASE_URL")
    if not dsn or not plain_dsn(dsn).startswith("postgresql://"):
        print("ERROR: a PostgreSQL DSN is required (--dsn or SION_DATABASE_URL)", file=sys.stderr)
        return 2
    try:
        if args.status:
            print(status(dsn, schema=args.regulation_schema, with_age=args.with_age))
            return 0
        core = apply_core(dsn, with_age=args.with_age)
        print(f"core: applied {len(core)} migration(s): {', '.join(core) or '-'}")
        if not args.skip_regulation:
            reg = apply_regulation(dsn, schema=args.regulation_schema)
            print(f"regulation ({args.regulation_schema}): applied {len(reg)} migration(s): {', '.join(reg) or '-'}")
        return 0
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
