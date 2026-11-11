# packages/

Sion is one Python distribution (`sion-ontology-platform`) built from several
import packages. Every package lives in its own folder; heavy third-party
libraries are optional extras and are imported lazily inside the functions that
need them (`sion_core.require()` gives an actionable error naming the extra).

| Folder | Import package | Purpose | Optional extra |
|---|---|---|---|
| `../apps/api` | `sion_api` | FastAPI canonical API | – |
| `core/` | `sion_core` | dependency-free helpers (optional-extra registry, lazy import) and `sion_core.contracts`: JSON Schemas for the bridged repos ([docs/INTEGRATION_CONTRACTS.md](../docs/INTEGRATION_CONTRACTS.md)) | – (`jsonschema` from `test` to validate) |
| `ingestion/` | `sion_ingestion` | map import, documents (md/txt/csv, DOCX, PDF), agent logs, advisory memory, project contracts | `documents` (PDF; DOCX has a built-in reader) |
| `cad/` | `sion_cad` | **the one DXF reading path** (`sion_cad.reader`: ezdxf strict → recover, CP949 detection, built-in text fallback; `dxf_census` in the All-In-Cad evidence shape), Sion DXF ingestion, GOD-CAD analysis bridge (`sion_cad.analysis`) | `cad` |
| `cad/god-cad/` | `god_cad` | GOD-CAD evidence-linked DXF analysis: stable entity identities, 2D geometry subset (mm), layer-prior semantic candidates, endpoint topology, edit-plan simulation. Merged with full history via `git subtree` from khs0927/GOD-CAD | `cad` |
| `bim/` | `sion_bim` | IFC parsing + ingestion (ifcopenshell, builtin STEP fallback) | `bim` |
| `cair/` | `sion_cair` | read-only AEC/CAIR federation over MCP stdio; `SION_AEC_ONTOLOGY_ROOT=bundled` runs the in-repo `aec_intelligence` | – |
| `aec/` | `aec_intelligence` | khs0927/Ontology AEC engine: DXF/IFC/PDF/raster adapters, CAIR, classifier, compliance, MCP gateway, operational stack. Merged with full history via `git subtree` (binary blobs excluded) | `cad`, `bim` (+ its own extras, see `packages/aec/pyproject.toml`) |
| `drive-store/` | `sion_drive_store` | content-addressed artifact lake, Drive publish (one-way, backup-before-replace into `.history/`) and service-account upload | `drive` |
| `graphrag/` | `sion_graphrag` | LightRAG GraphRAG projection, Apache AGE projection | `rag` |
| `regulation/` (docs only) | `archontos` — **external dependency**, not vendored | ArchOntos regulation fabric: evidence, assertions + review, rule DSL compiler/evaluator, outbox, RLS. Installed from khs0927/ArchOntos at the commit pinned in `pyproject.toml` ([regulation/README.md](regulation/README.md)) | `regulation` |

Legacy import paths keep working: `sion_ingestion.dxf_ingest` → `sion_cad.dxf`,
`sion_ingestion.ifc_ingest` → `sion_bim.ifc`, `sion_ingestion.aec_cair` →
`sion_cair.adapter` (module aliases, same objects).

## Extras

```bash
pip install -e .                    # core: API + ingestion, SQLite/PostgreSQL
pip install -e '.[cad]'             # + ezdxf
pip install -e '.[bim]'             # + ifcopenshell
pip install -e '.[rag]'             # + LightRAG, asyncpg, pgvector
pip install -e '.[drive]'           # + Google Drive API client
pip install -e '.[regulation]'      # + archontos (pinned git dependency) and its service deps
pip install -e '.[all,dev]'         # everything + pytest/httpx/ruff/build
uv sync --locked --extra all --extra dev   # reproducible install from uv.lock
```

The 0.1.x extra names `dxf`, `ifc`, `graphrag` remain as aliases.
`GET /api/v1/system/extras` reports which extras are installed without importing them.

## packages/regulation (ArchOntos)

ArchOntos is **not** copied into this repository any more. khs0927/ArchOntos is the single
source of truth; the `regulation` extra installs it as
`archontos @ git+https://github.com/khs0927/ArchOntos@<sha>` (pin in the root `pyproject.toml`
and [docs/INTEGRATION_CONTRACTS.md](../docs/INTEGRATION_CONTRACTS.md)). Change ArchOntos code in
that repository, then bump the pin. `tests/test_archontos_dependency.py` fails if an
`archontos` package with `.py` files reappears under `packages/`, and checks the installed
commit matches the pin. Details: [regulation/README.md](regulation/README.md).

## packages/aec (khs0927/Ontology) and packages/cad/god-cad (khs0927/GOD-CAD)

Both keep their own `pyproject.toml`, tests and docs, and run in
`.github/workflows/aec.yml`. History is preserved (`git log -- packages/aec`).
For packages/aec the history was imported from a local `git filter-repo` copy
without binary blobs (`*.parquet` regenerable exports, the `simple_house.dwg`
fixture and a `.bin` fixture); DWG tests that need the real file skip. The
upstream repositories were not modified.

DXF reading is consolidated: `aec_intelligence.dxf.read_dxf`,
`god_cad.adapters.dxf` and `sion_cad.dxf` all call `sion_cad.reader`. The
built-in fallback parser matches ezdxf item-for-item on all nine Korean
drawing fixtures (including the CP949 one). The aec api/worker image is now
built from the monorepo root:
`docker build -f packages/aec/docker/Dockerfile.app .` (compose updated).

Entry points installed by the root distribution: `god-cad`, `aec`, `aec-mcp`,
`aec-mcp-http`, `sion-migrate`.
