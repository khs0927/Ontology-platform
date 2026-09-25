# Sion Ontology Platform

Local-first ontology, knowledge graph, and multi-agent session ingestion. The current P0 remediation branch is an intermediate implementation, not a production release. GraphRAG, CAD, and BIM are planned boundaries; evidence persistence/contracts are present, but end-to-end document extraction is not complete.

- Code history: Git/GitHub (`khs0927/Ontology-platform`)
- Active editing: local disk on each computer
- Runtime database: local PostgreSQL with SQLite for smoke tests
- Drive role: artifact staging, logical dumps, manifests, and recovery copies; not a live database
- Current status and release gate: [docs/STATUS.md](docs/STATUS.md)

## Current state

Implemented foundations include the LinkML/SHACL contract, PostgreSQL schema and migration contract, API CRUD/query and vector routes, provenance/evidence persistence contracts, map-import safety, artifact metadata/staging, and non-destructive local sync.

Partial or still in progress include local bearer authentication, Alembic branch work, DLP scanning and the ingestion gate, and atomic Drive-side staging. Three agent readers are implemented (Antigravity, Codex, Claude); DeepSeek, Hermes, and ZCode are explicit stubs. Evidence records can be stored, but document extraction and end-to-end evidence creation are incomplete.

Production release remains blocked by outstanding release evidence, hosted CI billing limitation, and the prohibition on shipping an unsigned Windows EXE. See the [implementation/partial/planned matrix](docs/STATUS.md#implementation-partial-planned-matrix) and [verification baseline](docs/STATUS.md#verification-baseline).

## Multi-agent Session Bridge

The bridge discovers local agent sessions and emits the existing portable map/export artifacts. It is not a claim that every provider or extraction path is production-ready.

Supported readers:
- Google Antigravity: local session transcripts and artifacts (`~/.gemini/antigravity/brain`)
- OpenAI Codex: rollout logs (`~/.codex/sessions`)
- Anthropic Claude Code: transcripts (`~/.claude/transcripts`)
- DeepSeek, Hermes, ZCode: registered stubs pending implementation

### Run

```bash
python scripts/run_agent_bridge.py
```

Optional daemon mode:

```bash
python scripts/run_agent_bridge.py --daemon --interval 300
```

The bridge may detect a local Google Drive root and write logical dumps/JSON artifacts. It does not guarantee an authenticated Drive uploader, automatic scheduler registration, or a production backup service.

## Sync and API

See [sync/README.md](sync/README.md) and [apps/api/README.md](apps/api/README.md) for existing usage and the current local boundaries. Sync is one-way, non-destructive, checksum-manifest based, and uses atomic file replacement for local staging. The API is intended for loopback use in this branch; public deployment is not approved.

## Verification

Use the single verification source in [docs/STATUS.md](docs/STATUS.md#verification-baseline). The latest local run collects 357 tests with 0 failures, plus some environment-dependent skips; that is a recorded local observation, not a release gate. Run the commands from that section and record their result separately.

## Integration policy

The existing `khs0927/Ontology` repository is integrated through adapters only after compatibility and license checks. AEC/CAIR remains optional. GraphRAG and CAD/BIM ingestion are planned and are not end-to-end features in this branch.
