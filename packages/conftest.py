"""Root-level collection rules for subtree test suites under packages/.

`pytest` from the repository root collects packages/* (see pyproject testpaths).
Suites whose runtime needs are not part of the default test install are skipped
here; their own CI workflows (e.g. .github/workflows/regulation.yml) still run them.
"""

import importlib.util

collect_ignore_glob = [
    # Needs Postgres/pgvector/MinIO + pytest-asyncio; run by regulation.yml.
    "regulation/tests/integration",
]

_REGULATION_DEPS = ("asyncpg", "pydantic_settings", "prometheus_client", "greenlet")
if any(importlib.util.find_spec(m) is None for m in _REGULATION_DEPS):
    # Install the `regulation` extra to run these from the repo root.
    collect_ignore_glob.append("regulation/tests/*")
