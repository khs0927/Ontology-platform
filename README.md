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

## API security / remote access

Sion fails closed for network access.

- Default `SION_API_AUTH_MODE=local`: only loopback clients can use `/api/v1/*`; remote clients receive `403`.
- `SION_API_AUTH_MODE=token`: every `/api/v1/*` request requires a Bearer token, including local clients.
- `/health` is the only public route. CORS preflight (`OPTIONS`) is allowed, but the real request is still authenticated.
- Unknown API routes are denied by the firewall rather than exposed accidentally.

Token scopes are configured only through the environment:

```powershell
$env:SION_API_AUTH_MODE = "token"
$env:SION_API_TOKENS_JSON = '{"power-cad-token":["read:aec"],"admin-token":["*"]}'
```

Supported scopes:

- `read:aec`: `/api/v1/aec/*`
- `read:graph`: graph and vector-search reads
- `read:schema`: ontology schema and bootstrap inventory
- `read:knowledge`: entity/relation/evidence/artifact reads
- `write:knowledge`: entity/relation/evidence/artifact/embedding writes
- `*`: all currently exposed API scopes

Do not put bearer tokens in source, GitHub Actions YAML, Google Drive manifests, or CAIR/provenance files.

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
