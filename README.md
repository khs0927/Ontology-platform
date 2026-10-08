# Sion Ontology Platform

Local-first ontology / knowledge graph / GraphRAG platform with automated multi-agent session ingestion, evidence tracking, and cross-device Google Drive persistence.

Current milestone: monorepo consolidation (v0.2.0) — regulation, AEC and GOD-CAD merged; bridged repos on versioned contracts.

- **Code history**: Git/GitHub (`khs0927/Ontology-platform`)
- **Active editing**: Local disk on each computer
- **Automatic safety copy**: Google Drive `.CODE/_sync-v2/devices/<device-id>/...`
- **Validated release snapshots**: Google Drive `.CODE/_sync-v2/canonical/...`
- **AEC knowledge/artifacts**: Google Drive `AEC-INTELLIGENCE/` (`03_KNOWLEDGE_GRAPH`, `09_AGENT_MEMORY`, `10_EXPORTS`)
- **Runtime database**: Local PostgreSQL / SQLite truth store with portable PostgreSQL DDL/DML dumps (`sion_pg_knowledge_graph.sql`)

---

## Multi-Agent Session Bridge (Cross-Device Ingestion)

This platform automatically discovers and ingests interaction sessions from multiple local coding agents into the Sion Core Ontology graph without manual configuration.

### Supported Agents
- **Google Antigravity**: Local session transcripts and artifacts (`~/.gemini/antigravity/brain`)
- **OpenAI Codex**: Rollout session logs (`~/.codex/sessions`)
- **Anthropic Claude Code**: Conversation transcripts (`~/.claude/transcripts`)
- **Extensible Pluggable Readers**: Stubs ready for DeepSeek, Hermes Agent, ZCode in `sion_ingestion/agent_bridge.py`.

### Quick Execution on Any Computer

1. **One-shot sync**:
   ```bash
   python scripts/run_agent_bridge.py
   ```
   * Automatically discovers local agent logs.
   * Auto-detects Google Drive location (Windows drive letters, macOS CloudStorage, Linux paths).
   * Generates `sion_pg_knowledge_graph.sql` (PostgreSQL dump) and `sion_knowledge_graph.json`.
   * Tags all nodes with the unique machine `device_id` to eliminate multi-computer collisions.

2. **Automated Background Sync Setup (Any Computer)**:
   * **Windows**:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\scripts\install-agent-sync.ps1
     ```
   * **Linux / macOS**:
     ```bash
     bash ./scripts/install-agent-sync.sh
     ```
   * Or run in daemon mode:
     ```bash
     python scripts/run_agent_bridge.py --daemon --interval 300
     ```

---

## Integration Policy

This repository is the **main monorepo**. ArchOntos (`packages/regulation`), Ontology / `aec_intelligence`
(`packages/aec`) and GOD-CAD (`packages/cad/god-cad`) were merged with full history via `git subtree`
(see [`packages/README.md`](packages/README.md)). Six repositories stay separate and are **bridged by
versioned contracts**: power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad and CAD-MCP.
See [`docs/INTEGRATION_CONTRACTS.md`](docs/INTEGRATION_CONTRACTS.md). JSON Schemas ship in
`sion_core.contracts` and are covered by `tests/test_integration_contracts.py`. Live runtime databases
stay local; Google Drive receives logical dumps, snapshots, and canonical manifests.

### AEC/CAIR federation

`sion_cair.AecCairAdapter` talks to `aec_intelligence` through its `aec-mcp` stdio boundary, read-only.
It does not import CAIR rows into Sion automatically and it cannot call mutating tools. Use the bundled
copy, or an external Ontology checkout:

```powershell
$env:SION_AEC_ONTOLOGY_ROOT = "bundled"            # in-repo packages/aec (python -m aec_intelligence.mcp_stdio)
# or: $env:SION_AEC_ONTOLOGY_ROOT = "C:\CODE\Ontology"; $env:SION_AEC_MCP_COMMAND = "aec-mcp"
```

Allowed federation calls are limited to `aec.get_object`, `aec.query_global_memory`, `aec.graph_backend_plan`,
and the in-memory `aec.graph_hydradb_preview`. Canonical Sion persistence remains independent.
`GET /api/v1/aec/query` answers power-cad-mcp's `cad_context_query` with `canonical: false, read_only: true`.

### Regulation facts from korean-land-mcp

`POST /api/v1/regulation/evaluate` accepts `land_parcel` (a korean-land-mcp `analyze_parcel` record) and
turns it into fail-closed `land.*` facts for the ArchOntos rule evaluator. Overlay absences that cannot
be verified (point lookup, layer errors) are withheld, so the rule returns REVIEW.

### API security

Sion is local-only by default. Token-free API access requires a loopback client, a local request address,
and a trusted browser origin. Remote clients require bearer authentication.
Allow additional browser clients explicitly with `SION_CORS_ORIGINS`; see [security and privacy](SECURITY.md).

For remote access, configure scoped bearer authentication:

```powershell
$env:SION_API_AUTH_MODE = "bearer"
$env:SION_API_TOKENS_JSON = '{"replace-with-long-token":["read:aec","read:knowledge"],"replace-with-admin-token":["*"]}'
```

Supported scopes:
- `read:aec` — AEC/CAIR federation status and queries.
- `read:knowledge` — ontology schema, inventories, entities, relations, evidence, graph, artifacts, and vector search.
- `write:knowledge` — entity/relation/evidence/artifact/embedding writes.
- `*` — all scopes.

`local-or-bearer` is also available when loopback access should remain token-free while remote callers use bearer tokens. Tokens are compared in constant time and are never written to API responses.



### Temporal knowledge

Relations use half-open validity intervals: `[valid_from, valid_to)`.

- `GET /api/v1/relations?at=<ISO-8601>` returns relations valid at a historical instant.
- `GET /api/v1/relations?active_only=true` returns relations valid now.
- `GET /api/v1/graph?at=...` and `active_only=true` apply the same temporal filter to graph edges.
- `POST /api/v1/relations/{relation_id}/invalidate` closes an open relation with an explicit `valid_to` and optional reason.
- An already-invalidated relation cannot be silently rewritten.
- Invalidation before `valid_from` is rejected.
- Temporal comparisons are normalized to UTC; SQLite timestamps read back without tzinfo are interpreted as UTC.

This keeps superseded design facts queryable for permit/construction revisions without treating old facts as currently valid.

## Gap fill

- `POST /api/v1/ingest/documents` `{paths:[...]}` — md/txt/csv, unverified evidence
- `POST /api/v1/ingest/dxf` `{path}` — TEXT/INSERT/LINE/LWPOLYLINE
- `GET /map` — graph view over `/api/v1/graph`
- DeepSeek/Hermes/ZCode local log readers
- `migrations/005_age_projection.sql` optional AGE graph
- `sion_drive_store.upload.publish_to_mounted_drive`
- `POST /api/v1/ingest/ifc` `{path}` — IFC via optional `ifcopenshell` (`pip install -e '.[ifc]'`), dependency-free STEP fallback otherwise; `GET /api/v1/ingest/ifc/status` reports which parser is active
- `sion_drive_store.upload.upload_with_service_account` — optional Drive API upload (`pip install -e '.[drive]'`, `SION_DRIVE_SERVICE_ACCOUNT=<path to key JSON>`, `SION_DRIVE_FOLDER_ID=<folder shared with the service account>`). Never deletes or overwrites; same-name/different-size files are reported as conflicts.

### Ingestion path confinement

Ingest routes read files on the server. Set `SION_INGEST_ROOTS` (OS path-separator list) to confine them. When `SION_API_AUTH_MODE` is `bearer` or `local-or-bearer` and no roots are set, ingest routes return 403.

### Packages and optional extras

See [`packages/README.md`](packages/README.md) for the package map.

| Extra | Library | Without it |
|---|---|---|
| `cad` (alias `dxf`) | ezdxf >=1.4.4 | built-in DXF text parser |
| `bim` (alias `ifc`) | ifcopenshell >=0.9 | built-in STEP text parser |
| `rag` (alias `graphrag`) | lightrag-hku 1.5.7, asyncpg 0.32.0, pgvector 0.5.0 | GraphRAG routes return 503 |
| `drive` | google-api-python-client >=2.201, google-auth >=2.60 | service-account upload unavailable; mounted-folder publish still works (changed Drive files are first copied to `.history/<UTC stamp>/`) |
| `regulation` | pydantic-settings, sqlalchemy[asyncio], asyncpg, … (ArchOntos services) | `/api/v1/regulation/evaluate` returns 503 |
| `documents` | pypdf >=6.19, python-docx >=1.2 | DOCX via the built-in OOXML reader; PDFs reported as `skipped` |
| `validation` | rdflib >=7.6, pyshacl >=0.40.1 | `GET /api/v1/validation/shacl` returns 503 |
| `all` | all of the above | |
| `test` | pytest, httpx, jsonschema (contract validation) | |
| `dev` | `test` + ruff 0.16.10, build 1.6.1 | |

```bash
pip install -e '.[all,dev]' && ruff check . && pytest && python -m build
# or, reproducibly from uv.lock
uv sync --locked --extra all --extra dev && uv run pytest
```

### Windows agent bridge binary

`sion-agent-bridge.exe` is published on [GitHub Releases](https://github.com/khs0927/Ontology-platform/releases)
by the `Release agent bridge` workflow; it is no longer committed. See [`bin/README.md`](bin/README.md).
