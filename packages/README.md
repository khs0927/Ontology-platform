# packages/

Sion is one Python distribution (`sion-ontology-platform`) built from several
import packages. Every package lives in its own folder; heavy third-party
libraries are optional extras and are imported lazily inside the functions that
need them (`sion_core.require()` gives an actionable error naming the extra).

| Folder | Import package | Purpose | Optional extra |
|---|---|---|---|
| `../apps/api` | `sion_api` | FastAPI canonical API | – |
| `core/` | `sion_core` | dependency-free helpers (optional-extra registry, lazy import) | – |
| `ingestion/` | `sion_ingestion` | map import, documents, agent logs, advisory memory, project contracts | – |
| `cad/` | `sion_cad` | DXF parsing + ingestion (ezdxf, builtin text fallback) | `cad` |
| `bim/` | `sion_bim` | IFC parsing + ingestion (ifcopenshell, builtin STEP fallback) | `bim` |
| `cair/` | `sion_cair` | read-only AEC/CAIR federation with khs0927/Ontology via MCP stdio | – |
| `drive-store/` | `sion_drive_store` | content-addressed artifact lake, Drive publish/upload | `drive` |
| `graphrag/` | `sion_graphrag` | LightRAG GraphRAG projection, Apache AGE projection | `rag` |

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
pip install -e '.[all,dev]'         # everything + pytest/httpx/ruff/build
uv sync --locked --extra all --extra dev   # reproducible install from uv.lock
```

The 0.1.x extra names `dxf`, `ifc`, `graphrag` remain as aliases.
`GET /api/v1/system/extras` reports which extras are installed without importing them.
