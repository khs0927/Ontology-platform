"""pgvector layout: one table per embedding space, so spaces can never be mixed by accident.

Only generates SQL; execution stays with the caller's migration tooling."""

from __future__ import annotations

import re

from .registry import ModelSpec

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def ddl(spec: ModelSpec, dim: int | None = None, schema: str = "embedhub", prefix: str = "vec") -> str:
    d = dim or spec.native_dim
    suffix = spec.space_id(d)
    table = f"{prefix}_{suffix}"[:63]
    for ident in (schema, table):
        if not _IDENT.match(ident):
            raise ValueError(f"unsafe identifier {ident!r}")
    return (
        f"CREATE SCHEMA IF NOT EXISTS {schema};\n"
        f"CREATE TABLE IF NOT EXISTS {schema}.{table} (\n"
        f"  item_id    text NOT NULL,\n"
        f"  modality   text NOT NULL CHECK (modality IN ('text','image')),\n"
        f"  source_ref text,\n"
        f"  embedding  vector({d}) NOT NULL,\n"
        f"  created_at timestamptz NOT NULL DEFAULT now(),\n"
        f"  PRIMARY KEY (item_id, modality)\n"
        f");\n"
        f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {schema}.{table} USING hnsw (embedding vector_cosine_ops);\n"
    ) if d <= 2000 else (
        # pgvector's hnsw/ivfflat index cap is 2000 dims for `vector`; use halfvec for larger spaces
        f"CREATE SCHEMA IF NOT EXISTS {schema};\n"
        f"CREATE TABLE IF NOT EXISTS {schema}.{table} (\n"
        f"  item_id    text NOT NULL,\n"
        f"  modality   text NOT NULL CHECK (modality IN ('text','image')),\n"
        f"  source_ref text,\n"
        f"  embedding  halfvec({d}) NOT NULL,\n"
        f"  created_at timestamptz NOT NULL DEFAULT now(),\n"
        f"  PRIMARY KEY (item_id, modality)\n"
        f");\n"
        f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {schema}.{table} USING hnsw (embedding halfvec_cosine_ops);\n"
    )
