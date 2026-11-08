"""Read-only CI diagnostics for a failed NVIDIA official semantic compilation.

Reports only synthetic catalog counts, never source values, model outputs,
credentials or container logs. Restricts connections to the isolated runner
loopback database created by nvidia-official-semantic-e2e.yml.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import psycopg

TABLES = ("catalog_database", "catalog_schema", "catalog_table",
          "catalog_column", "term", "semantic_compilation_history")


def env() -> dict[str, str]:
    if os.environ.get("GITHUB_REPOSITORY") != "khs0927/Ontology-platform":
        raise RuntimeError("repository gate failed")
    path = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia" / ".env"
    values = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        if row and not row.startswith("#"):
            key, _, value = row.partition("=")
            if key in ("POSTGRES_PASSWORD", "CONNECTION_STRINGS"):
                values[key] = value
    source = values.get("CONNECTION_STRINGS", "")
    if not source.startswith("postgresql://nvidia_pilot_reader:") or not source.endswith(
        "@postgres:5432/sion_nvidia_ci"
    ):
        raise RuntimeError("not the isolated read-only Sion source")
    if not values.get("POSTGRES_PASSWORD"):
        raise RuntimeError("missing synthetic Postgres password")
    return values


def main() -> int:
    values = env()
    with psycopg.connect(
        host="127.0.0.1", port=15432, dbname="sion_nvidia_ci",
        user="nvidia_pilot_reader", password="ci_only_test_password_0101",
        connect_timeout=6, autocommit=True,
    ) as src:
        rows = src.execute(
            "SELECT COUNT(*) FROM sion_nv_pilot.verified_project_objects"
        ).fetchone()[0]
        if rows != 2:
            raise RuntimeError("source fixture rows not equal to expected two")
    print("PASS isolated source: 2 authorized synthetic rows, no other schema readable")

    with psycopg.connect(
        host="127.0.0.1", port=15432, dbname="auto_ontology",
        user="sion_owner", password=values["POSTGRES_PASSWORD"],
        connect_timeout=8, autocommit=True,
    ) as catalog:
        status = {}
        for name in TABLES:
            # Table names are hard-coded, never drawn from external text.
            exists = catalog.execute(
                "SELECT to_regclass(%s) IS NOT NULL", ("public." + name,)
            ).fetchone()[0]
            if not exists:
                status[name] = "missing"
            else:
                count = catalog.execute(
                    "SELECT COUNT(*) FROM public." + name
                ).fetchone()[0]
                status[name] = int(count)
        print("CATALOG_ROWS:", " ".join(f"{k}={v}" for k, v in status.items()))
        flag = catalog.execute(
            "SELECT value FROM frontend.configurations WHERE key = %s",
            ("semantic_compilation_enabled",),
        ).fetchone()
        print("SEMANTIC_ENABLED:", (flag[0] if flag and flag[0] in ("true", "false") else "unknown"))
        if isinstance(status["semantic_compilation_history"], int):
            grouped = catalog.execute(
                "SELECT COALESCE(status, 'unfinished'), COUNT(*) "
                "FROM public.semantic_compilation_history "
                "GROUP BY COALESCE(status,'unfinished') ORDER BY 1"
            ).fetchall()
            print("COMPILATION_HISTORY:", " ".join(
                f"{key}={int(total)}" for key, total in grouped
            ) or "none")
    print("Diagnostic complete. No real Sion data or credentials accessed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, psycopg.Error) as exc:
        print("CATALOG_DIAGNOSTIC_FAILURE:", type(exc).__name__)
        sys.exit(1)
