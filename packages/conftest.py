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

import sys

if importlib.util.find_spec("ezdxf") is None:
    # CAD suites need ezdxf (the `cad` extra); aec.yml and the GOD-CAD workflow
    # run them with their own installs.
    collect_ignore_glob += ["cad/*", "aec/tests/*"]

if sys.platform == "win32":
    # These aec suites assume POSIX paths/console encoding and are only run on
    # Linux by aec.yml; drawing_context stays cross-platform (headless workflow).
    collect_ignore_glob += ["aec/tests/*", "aec/extensions/intelligence_fabric/*"]

import sqlite3

if sqlite3.sqlite_version_info < (3, 39, 0):
    # The SQLite shim in this suite relies on `IS [NOT] DISTINCT FROM` (SQLite
    # 3.39+); older system SQLite (e.g. cimg/python on CircleCI) cannot parse it.
    collect_ignore_glob.append("aec/tests/test_embedding_state.py")
