# Storage root on Google Drive

Platform **assets** live directly in one folder on Google Drive for desktop (the storage root).
The **live database** stays on a local disk and is exported to the storage root after every write.
No scheduled copy job is involved.

```
G:\내 드라이브\AEC-INTELLIGENCE\01_PROJECTS\SION-ONTOLOGY\   <- SION_STORAGE_ROOT
  00_SOURCES\                raw sources and the content-addressed artifact lake
    sketchup\0914-meeting\   model_dump.json, geometry_probe.json, grouping_probe.json,
                             classification.json, renders\*.png
    sketchup\scripts\        read-only Ruby extraction scripts
    objects\sha256\..        sion_drive_store content-addressed objects (+ manifests\)
  01_SNAPSHOTS\db\           sion-<UTC>.db (newest 20 kept), sion-latest.db, sion-latest.sql
                             (PostgreSQL: sion-<UTC>.dump / sion-latest.dump via pg_dump)
  02_EXPORTS\graph\          sion-graph-latest.json (whole graph, sion-map-export/v1, re-importable)
                             sion-evidence-latest.jsonl (every evidence row)
  02_EXPORTS\bootstrap\      generated graph packs (e.g. sketchup-0914-meeting.json)
  02_EXPORTS\agent-bridge\   agent-session export written by scripts/run_agent_bridge.py (uses $SION_DATABASE_URL)
  03_DOCS\                   knowledge documents (guidelines, workflows, architecture notes)
  09_AGENT_MEMORY\           agent memory exports
  storage-manifest.json      layout, last export (counts + SHA-256 per file), last asset placement
```

## Configuration

| Variable | Meaning |
| --- | --- |
| `SION_STORAGE_ROOT` | the storage root itself |
| `SION_DRIVE_ROOT` / `GOOGLE_DRIVE_ROOT` | My Drive; the root becomes `<drive>/AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY` |
| `SION_DRIVE_EXPORT_ON_WRITE` | `1` (default when a root is set) or `0` |
| `SION_DRIVE_EXPORT_DEBOUNCE_S` | wait this long for more writes before exporting (default 5) |
| `SION_DRIVE_SNAPSHOT_KEEP` | timestamped DB snapshots to keep (default 20; only `sion-<UTC>.db/.dump` files are pruned) |
| `SION_DATABASE_URL` | the live DB, **on a local disk** (default `sqlite:///<repo>/runtime/sion.db`) |
| `SION_SU_EXPORT_DIR` | where the SketchUp Ruby scripts write; point it at `00_SOURCES\sketchup\<model>` |

## Running it on Windows

```powershell
.\scripts\sion-local.ps1 start    # local embeddings (if configured) + API on 127.0.0.1:8010
.\scripts\sion-local.ps1 status   # health, storage root, last export
.\scripts\sion-local.ps1 stop     # writes a final export to the storage root, then stops
```

## How the export works

`sion_api.drive_export` installs `before_flush` / `after_commit` hooks on the session factory.
A commit that inserted, updated or deleted anything schedules one debounced export:

1. **DB snapshot**: SQLite online backup API (consistent while the API keeps writing) into a
   local temp file, then copied next to the target under a temporary name and renamed over it.
   PostgreSQL uses `pg_dump -Fc` when it is on `PATH`.
2. **Graph export**: every entity and relation as `sion-map-export/v1` JSON, plus the evidence rows
   as JSONL, so the graph can be re-imported without the DB file.
3. **Manifest**: counts and SHA-256 of each written file in `storage-manifest.json`.

One-shot CLIs (`sion-relations import`, `python -m sion_ingestion.sketchup_assets import`) export
once at the end. Status and a forced export:

- `GET /api/v1/storage/status` (`read:knowledge`)
- `POST /api/v1/storage/export` (`write:knowledge`)
- `python -m sion_api.drive_export layout --create | snapshot | publish-assets`

`publish-assets` places the repo's committed assets (SketchUp sources and scripts, bootstrap packs,
knowledge docs) under the root. It skips identical files and never deletes anything.

## Why the live DB is not on G:

Google Drive for desktop streams files and uploads them while they change. A SQLite file with
its `-wal`/`-journal`, or a PostgreSQL data directory, can be uploaded half-written, replaced by
a conflict copy, or evicted to the cloud while open. That corrupts the database, and a second
device opening the same file makes it worse. The repo keeps the live DB local
(`docs/SYNC_ARCHITECTURE.md`) and writes consistent snapshots to Drive on every change instead,
so the newest state is always on G: without the database itself living there.

To restore or move to another PC: copy `01_SNAPSHOTS\db\sion-latest.db` to a local disk and set
`SION_DATABASE_URL=sqlite:///<that path>`. You can also import `02_EXPORTS\graph\sion-graph-latest.json`
into any database with `sion-relations import ... --verified`, because the export keeps each
relation's verification state.

## Bootstrap snapshot manifest (read-only, issue #71 step B)

Before data is migrated or bootstrapped onto another machine, describe exactly what is being
moved and check it again on arrival. `sion_drive_store.bootstrap_snapshot` does this without
writing to the source:

```bash
# on the source machine: describe an export folder (snapshots + graph export), write the manifest elsewhere
python -m sion_drive_store.bootstrap_snapshot create --root <export-dir> \
    --created-at 2026-11-05T00:00:00Z --out <manifests>/bootstrap-20261105.json [db graph ...]

# after copying: recompute everything; exit 1 on any mismatch, 2 when the snapshot is refused
python -m sion_drive_store.bootstrap_snapshot verify <manifests>/bootstrap-20261105.json --root <copied-dir>
```

The `sion-bootstrap-snapshot/v1` manifest lists, per file, a root-relative `source_uri`
(`snapshot:db/sion-latest.db`), `size_bytes` and `sha256`, plus:

| File | Extra facts |
| --- | --- |
| SQLite (detected by header) | `open_uri` (`file:<name>?mode=ro`), `row_counts` per table, `schema.user_version`, recorded migrations (`sion_schema_migrations`, `schema_migrations`, `alembic_version`), `schema.sqlite_master_sha256` |
| `sion-map-export/v1` JSON | `row_counts.nodes` / `edges`, `export_source`, `ontology_versions` |
| `.jsonl` (e.g. evidence) | `row_counts.records` |
| CAD original, only with `--allow-cad-hash-only` | `kind: cad-original`, `hash_only: true` (size and SHA-256, nothing else) |

`created_at` is passed in (timezone-aware ISO-8601), so the same inputs give the same manifest.
`content_sha256` covers the file list, so an edited manifest fails verification too.

Fail-closed rules:

- SQLite is opened with `mode=ro` and `PRAGMA query_only`; every file is hashed before and after
  it is read, and a file that changed meanwhile aborts the run. `PRAGMA quick_check` must be `ok`.
- A database with a non-empty `-wal`/`-journal` file is treated as live and refused: snapshot it
  first (`python -m sion_api.drive_export snapshot`) and point the tool at the copy.
  `-wal`/`-shm`/`-journal` sidecars are never listed.
- `.dwg`, `.dxf`, `.skp`, `.skb`, `.bak`, `.dwl`, `.dwl2` are refused unless `--allow-cad-hash-only`.
- Secrets (`.env*`, `*.pem`, `*.key`, `id_rsa*`, credential/client-secret/service-account/token
  JSON, `.netrc`, `.pgpass`, ...) are refused when named and skipped inside folders; VCS folders,
  virtualenvs, caches and symlinks are skipped. Only counts per reason appear in `excluded`.
- A map export whose `expected_node_count`/`expected_edge_count` disagrees with its content is refused.
- Sources must lie inside `--root`; the manifest contains no absolute paths. `--out` must be a new
  file outside every source (no overwrite).

## What needs a running service

| Task | Needs |
| --- | --- |
| Read assets on G:, `sketchup_assets build --check`, tests | nothing |
| Import packs and evidence (`... import --database-url sqlite:///...`) | nothing running; a local SQLite file is enough |
| `/review` UI, REST API, `POST /api/v1/graphrag/project`, `/query` | the Sion API (`uvicorn`) |
| GraphRAG retrieval | the API and an embedding endpoint (`scripts/local_embeddings.py` runs one locally); `SION_GRAPHRAG_STORAGE=local` works without PostgreSQL |
| AGE/pgvector graph projection, `vector/search`, `regulation` schema, multi-user writes | PostgreSQL with AGE and pgvector |
