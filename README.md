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
