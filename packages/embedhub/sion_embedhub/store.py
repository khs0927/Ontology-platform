"""pgvector layout: one table per embedding space, so spaces can never be mixed by accident.

Only generates SQL; execution stays with the caller's migration tooling.

Index limits matter here: pgvector's HNSW/IVFFlat indexes support at most 2000 dimensions for
``vector`` and 4000 for ``halfvec``. Above that the column is still created, but no ANN index is
emitted: queries fall back to an exact sequential scan (correct, just slower).
"""

from __future__ import annotations

import re

from .registry import ModelSpec

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# pgvector limits per column type (dims for a usable hnsw/ivfflat index)
ANN_MAX_DIMS = {"vector": 2000, "halfvec": 4000}


def ddl(spec: ModelSpec, dim: int | None = None, schema: str = "embedhub", prefix: str = "vec") -> str:
    d = dim or spec.native_dim
    suffix = spec.space_id(d)
    table = f"{prefix}_{suffix}"[:63]
    for ident in (schema, table):
        if not _IDENT.match(ident):
            raise ValueError(f"unsafe identifier {ident!r}")
    col_type = "vector" if d <= ANN_MAX_DIMS["vector"] else "halfvec"
    opclass = "vector_cosine_ops" if col_type == "vector" else "halfvec_cosine_ops"
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {schema};",
        f"CREATE TABLE IF NOT EXISTS {schema}.{table} (",
        "  item_id    text NOT NULL,",
        "  modality   text NOT NULL CHECK (modality IN ('text','image')),",
        "  source_ref text,",
        f"  embedding  {col_type}({d}) NOT NULL,",
        "  created_at timestamptz NOT NULL DEFAULT now(),",
        "  PRIMARY KEY (item_id, modality)",
        ");",
    ]
    if d <= ANN_MAX_DIMS[col_type]:
        stmts.append(f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {schema}.{table} "
                     f"USING hnsw (embedding {opclass});")
    else:
        stmts.append(f"-- no ANN index: pgvector supports at most {ANN_MAX_DIMS[col_type]} dimensions for a "
                     f"{col_type} HNSW index, but this space is {d}d; exact search (sequential scan) is used.")
    return "\n".join(stmts) + "\n"
