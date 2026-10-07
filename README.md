# Sion Ontology Platform

Local-first ontology / knowledge graph / GraphRAG platform with automated multi-agent session ingestion, evidence tracking, and cross-device Google Drive persistence.

Current milestone: safe cross-device persistence & multi-agent real-data ingestion.

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

The existing `khs0927/Ontology` repository is integrated through adapters only after individual components pass compatibility and license checks. Live runtime databases stay local; Google Drive receives logical dumps, snapshots, and canonical manifests.

### AEC/CAIR federation

The ingestion package now includes a read-only `AecCairAdapter` that talks to the public `khs0927/Ontology` repository through its `aec-mcp` stdio boundary. It does not import CAIR rows into Sion automatically and it cannot call mutating Ontology tools.

Configure it only on a machine that has the Ontology checkout and `aec-mcp` available:

```powershell
$env:SION_AEC_ONTOLOGY_ROOT = "C:\\CODE\\Ontology"
$env:SION_AEC_MCP_COMMAND = "aec-mcp"
```

Allowed federation calls are limited to `aec.get_object`, `aec.query_global_memory`, `aec.graph_backend_plan`, and the in-memory `aec.graph_hydradb_preview`. Canonical Sion persistence remains independent.


### API security

Sion is local-only by default. Requests to `/api/v1/*` from loopback clients work without a token, while remote clients are rejected.

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
- `POST /api/v1/ingest/ifc` `{path}` — IFC products/spatial elements (IfcOpenShell optional, STEP fallback)
- `GET /map` — graph view over `/api/v1/graph`
- DeepSeek/Hermes/ZCode local log readers
- `migrations/005_age_projection.sql` optional AGE graph
- `sion_drive_store.upload.publish_to_mounted_drive`

## Optional extras

```bash
pip install -e '.[test,cad,ifc,drive]'   # ezdxf, IfcOpenShell, Google Drive API
ruff check .                             # lint
python -m build                          # sdist + wheel
python scripts/build_exe.py              # PyInstaller agent bridge (bin/)
SION_TEST_AGE_URL=postgresql+psycopg://... python scripts/verify_age.py
```

Drive API upload: set `SION_DRIVE_SERVICE_ACCOUNT` (path to a service-account
JSON key, never committed) and `SION_DRIVE_ROOT_FOLDER_ID`.
