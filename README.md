# Sion Ontology Platform

## 건축·토지 규제 작업 전 필독

건축규제, 토지 중첩규제, 법령 온톨로지, GraphRAG 또는 규제 MCP 연결 작업은 먼저
[개발 지침과 읽기 순서](docs/regulation/DEVELOPMENT-GUIDELINES.md)를 읽으세요.
전체 프레임워크·벤치마킹·검증 계획을 연결한 문서입니다.
현재 단계는 **계획 수립**이며 개발·설치·마이그레이션·배포 착수는 별도 지시가 필요합니다.
계획 문서의 목표 기능과 현재 구현을 구분하세요. 에이전트 지침은 [AGENTS.md](AGENTS.md)에 있습니다.

Local-first ontology / knowledge graph / GraphRAG platform with automated multi-agent session ingestion, evidence tracking, and cross-device Google Drive persistence.

Current milestone: monorepo consolidation (v0.3.0) — regulation, AEC and GOD-CAD merged; bridged repos on versioned contracts. See [CHANGELOG.md](CHANGELOG.md).

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
- **DeepSeek / Hermes / ZCode**: Local JSON/JSONL log readers (`DeepSeekReader`, `HermesReader`, `ZCodeReader` in `sion_ingestion/agent_bridge.py`) discover provider dirs via env roots (`SION_DEEPSEEK_ROOT`, `SION_HERMES_ROOT`, `SION_ZCODE_ROOT`) with sensible home defaults. They run through the same CLI: `--provider all` (default) covers all six readers, or pick one with `--provider deepseek|hermes|zcode`.

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

This repository is the **main monorepo**. Ontology / `aec_intelligence` (`packages/aec`) and GOD-CAD
(`packages/cad/god-cad`) were merged with full history via `git subtree`
(see [`packages/README.md`](packages/README.md)). ArchOntos is consumed as a **pinned git dependency**
(`archontos`, `regulation` extra; pin in [`docs/INTEGRATION_CONTRACTS.md`](docs/INTEGRATION_CONTRACTS.md)). Five repositories stay separate and are **bridged by
versioned contracts**: power-cad-mcp, hs-steel-cad, korean-land-mcp, All-In-Cad and CAD-MCP.
HS-CAD is retired; power-cad-mcp is the only active CAD host bridge.
See [`docs/INTEGRATION_CONTRACTS.md`](docs/INTEGRATION_CONTRACTS.md). JSON Schemas ship in
`sion_core.contracts` and are covered by `tests/test_integration_contracts.py`. Assets live directly under
the Google Drive storage root (`SION_STORAGE_ROOT`, see [`docs/STORAGE.md`](docs/STORAGE.md)). The live
database stays on a local disk, and every committed write exports a DB snapshot plus the whole graph there.

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
- `read:knowledge` — every read-only knowledge route: ontology schema, inventories, entities, relations, review candidates, evidence, graph, artifacts, vector search and GraphRAG queries.
- `write:knowledge` — every write: entity/relation/evidence/artifact/embedding writes, relation review decisions, imports and ingestion.
- `*` — all scopes.
- `project:<uuid>` — optional project ACL entry. A token that lists one or more `project:` entries is limited to those projects on `GET /api/v1/regulation/summary` only; malformed entries grant nothing. Tokens without `project:` entries, `*` tokens and trusted local requests are unrestricted.

> **Project scopes are not an isolation boundary yet.** Only the summary route enforces them. A project-scoped
> token that also holds `read:knowledge` can still read every project's full reports through
> `GET /api/v1/regulation/works` and the other `read:knowledge` routes. Do not issue such a token to a party that
> must be confined to its projects; enforcing the ACL on the remaining per-project read routes is follow-up work.

Scopes are disjoint: `write:knowledge` does not imply `read:knowledge`. A token can also be limited to
specific projects with `{"scopes": [...], "projects": ["<project-uuid>"]}`. See
[API authorization](docs/API_AUTH.md) for the project ACL and the route-coverage test.

`local-or-bearer` is also available when loopback access should remain token-free while remote callers use bearer tokens. Tokens are compared in constant time and are never written to API responses.

### Mobile project summary (read-only)

`GET /api/v1/regulation/summary` returns a small per-project overview of saved regulation reviews for mobile
clients. Unlike `GET /api/v1/regulation/works`, it never returns stored report payloads, notes or tasks: each item
carries `project_id`, `project_name`, `work_count`, `status_counts` (`open`/`in_review`/`done`) and `latest_work`
(`id`, `title`, `status`, `decision_status`, `as_of`, `updated_at`). Responses are `read_only: true, canonical: false`.

- Auth: requires `read:knowledge`. With a project-scoped token, requesting a disallowed `project_id` returns 403
  before any database read; without a filter only the token's projects are listed.
- Filter: repeatable `project_id=<uuid>` (at most 50).
- Pagination: keyset cursor. `limit` defaults to 20 (max 50); pass the returned `next_cursor` as `cursor` until it is `null`.
- Size bound: the body stays under `SION_SUMMARY_MAX_BYTES` (default 65536, minimum 4096). When the bound cuts a
  page short, `truncated` is `true` and `next_cursor` resumes after the last returned project. Names are clipped to 200 characters;
  an item that alone would not fit is replaced by `{"project_id": ..., "item_truncated": true}`.
- Rate limit: in-process sliding window per client (digest of the matched configured token, else peer address for
  trusted local requests), configured with
  `SION_SUMMARY_RATE_LIMIT=<requests>/<seconds>` (default `60/60`, `0` disables). Excess requests get 429 with
  `Retry-After`. The limiter is per process and is not shared between workers.



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
- DeepSeek/Hermes/ZCode local JSON/JSONL log readers (registered in `PROVIDER_REGISTRY`)
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
| `regulation` | `archontos` (pinned git dependency) + pydantic-settings, sqlalchemy[asyncio], asyncpg, … | `/api/v1/regulation/evaluate` returns 503 |
| `documents` | pypdf >=6.19, python-docx >=1.2 | DOCX via the built-in OOXML reader; PDFs reported as `skipped` |
| `hwp` | hwp-hwpx-parser >=1.0 (Apache-2.0) | HWPX via the built-in reader; `.hwp` reported as `skipped` |
| `ocr` | pypdfium2 >=5 | scanned PDFs reported as `skipped` (images still OCR when an endpoint is set); see [`docs/INGESTION.md`](docs/INGESTION.md) |
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

## MCP 운영 지침과 스킬 (Local CAD/AEC MCP)

로컬 CAD/AEC MCP 서버(SketchUp, Revit/Horizun, AutoCAD, power-cad, ZWCAD, FreeCAD, Rhino 등)와 MCP 클라이언트
설정을 다루는 한국어 지침·스킬·도구입니다. Sion 자체는 CAD를 변경하지 않으며, 아래는 사용자의 요청으로 에이전트가
CAD 앱을 직접 조작할 때의 규칙입니다.

- 지침 인덱스: [`docs/mcp/README.md`](docs/mcp/README.md)
  - [로컬 CAD MCP 운영](docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md) · [클라이언트 동기화](docs/mcp/MCP-CLIENT-SYNC.ko.md) ·
    [jev/TypeSafe](docs/mcp/JEV-TYPESAFE.ko.md) · [비밀값 취급](docs/mcp/SECRETS.ko.md) · [도구 카탈로그](docs/mcp/TOOL-CATALOG.ko.md)
- 스킬: [`skills/`](skills/README.md) — `local-cad-mcp-bridge`, `sketchup-mcp`, `mcp-client-sync`, `jev-decision`, `typesafe-ai`
- 도구: [`tools/grokbot-mcp-bridge/`](tools/grokbot-mcp-bridge/README.md) (Windows stdio MCP 브리지),
  [`tools/jev-mcp/`](tools/jev-mcp/README.md) (Jev stdio MCP 서버)
