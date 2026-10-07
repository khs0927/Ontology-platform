# Google Drive integration record

Created and verified on 2026-09-01 for the first DXF milestone, then extended
on 2026-09-02 for the ODA-backed DWG project. The latest canonical local state
is 3 projects, 229 artifacts, 163 objects, and 163 relations; the CLI-only GIS
smoke project remains archived outside `projects/` and is intentionally not
represented in Drive.

- Root: [AEC-INTELLIGENCE](https://drive.google.com/drive/folders/PRIVATE_DRIVE_ID)
- Project: [AEC-2026-000001_Simple-House](https://drive.google.com/drive/folders/PRIVATE_DRIVE_ID)
- Project: [AEC-2026-000003_Simple-House-003](https://drive.google.com/drive/folders/PRIVATE_DRIVE_ID)
- Project: [AEC-2026-000004_ODA-House-30-Pyeong](https://drive.google.com/drive/folders/PRIVATE_DRIVE_ID)
- Drive profile was successfully read back before repository creation.
- Drive visibility read-back: created folders report `not_shared`; no sharing or permission changes were made.

## Verified folder IDs

| Purpose | Drive folder ID |
| --- | --- |
| `00_GLOBAL` | `PRIVATE_DRIVE_ID` |
| `01_PROJECTS` | `PRIVATE_DRIVE_ID` |
| project `03_CAIR` | `PRIVATE_DRIVE_ID` |
| project `04_ONTOLOGY` | `PRIVATE_DRIVE_ID` |
| project `05_GRAPH` | `PRIVATE_DRIVE_ID` |
| project validation/parsing | `PRIVATE_DRIVE_ID` |
| global `08_VALIDATION` | `PRIVATE_DRIVE_ID` |
| global `09_AGENT_MEMORY` | `PRIVATE_DRIVE_ID` |
| global `10_EXPORTS` | `PRIVATE_DRIVE_ID` |
| project `06_MODELS/BLENDER` | `PRIVATE_DRIVE_ID` |
| project `06_MODELS/FREECAD` | `PRIVATE_DRIVE_ID` |
| project `02_DERIVED/BIM` | `PRIVATE_DRIVE_ID` |
| project `02_DERIVED/BIM/GLB` | `PRIVATE_DRIVE_ID` |
| project `02_DERIVED/BIM/STEP` | `PRIVATE_DRIVE_ID` |
| project `02_DERIVED/PREVIEWS` | `PRIVATE_DRIVE_ID` |
| project `11_VALIDATION/cross-format` | `PRIVATE_DRIVE_ID` |
| project `13_AGENT_MEMORY` | `PRIVATE_DRIVE_ID` |
| project `AEC-2026-000004` root | `PRIVATE_DRIVE_ID` |
| project `000004/00_MANIFEST` | `PRIVATE_DRIVE_ID` |
| project `000004/01_RAW` | `PRIVATE_DRIVE_ID` |
| project `000004/02_DERIVED` | `PRIVATE_DRIVE_ID` |
| project `000004/03_CAIR` | `PRIVATE_DRIVE_ID` |
| project `000004/04_ONTOLOGY` | `PRIVATE_DRIVE_ID` |
| project `000004/05_GRAPH` | `PRIVATE_DRIVE_ID` |
| project `000004/06_MODELS` | `PRIVATE_DRIVE_ID` |
| project `000004/07_GIS` | `PRIVATE_DRIVE_ID` |
| project `000004/10_ITERATIONS` | `PRIVATE_DRIVE_ID` |
| project `000004/11_VALIDATION` | `PRIVATE_DRIVE_ID` |
| project `000004/13_AGENT_MEMORY` | `PRIVATE_DRIVE_ID` |
| project `AEC-2026-000003` root | `PRIVATE_DRIVE_ID` |
| project `000003/00_MANIFEST` | `PRIVATE_DRIVE_ID` |
| project `000003/01_RAW/CAD/DXF` | `PRIVATE_DRIVE_ID` |
| project `000003/02_DERIVED/CAD/SVG` | `PRIVATE_DRIVE_ID` |
| project `000003/03_CAIR` | `PRIVATE_DRIVE_ID` |
| project `000003/03_CAIR/snapshots` | `PRIVATE_DRIVE_ID` |
| project `000003/03_CAIR/tables` | `PRIVATE_DRIVE_ID` |
| project `000003/04_ONTOLOGY` | `PRIVATE_DRIVE_ID` |
| project `000003/05_GRAPH` | `PRIVATE_DRIVE_ID` |
| project `000003/06_MODELS` | `PRIVATE_DRIVE_ID` |
| project `000003/07_GIS` | `PRIVATE_DRIVE_ID` |
| project `000003/10_ITERATIONS` | `PRIVATE_DRIVE_ID` |
| project `000003/11_VALIDATION` | `PRIVATE_DRIVE_ID` |
| project `000003/13_AGENT_MEMORY` | `PRIVATE_DRIVE_ID` |

## Verified artifact IDs

The DXF source, manifest, CAIR, ontology, SVG, and validation files were uploaded. The source file and all derived files were checked by folder read-back. Existing files were updated in place when the local snapshot was regenerated, preserving their Drive IDs and revision history.

| Artifact | Drive file ID |
| --- | --- |
| `simple_house.dxf` | `PRIVATE_DRIVE_ID` |
| `project-manifest.json` | `PRIVATE_DRIVE_ID` |
| `project-cair.json` | `PRIVATE_DRIVE_ID` |
| `geometry-index.jsonl` | `PRIVATE_DRIVE_ID` |
| `project.ttl` | `PRIVATE_DRIVE_ID` |
| `project.jsonld` | `PRIVATE_DRIVE_ID` |
| `nodes.jsonl` | `PRIVATE_DRIVE_ID` |
| `relationships.jsonl` | `PRIVATE_DRIVE_ID` |
| `simple_house.svg` | `PRIVATE_DRIVE_ID` |
| `validation-status.json` | `PRIVATE_DRIVE_ID` |
| `parse-report.json` | `PRIVATE_DRIVE_ID` |

The ODA-backed `AEC-2026-000004` project was synchronized as a 44-file
canonical package. Key artifact IDs are:

- Raw CAD: DWG `PRIVATE_DRIVE_ID`, DXF `PRIVATE_DRIVE_ID`.
- Manifest/CAIR: manifest `PRIVATE_DRIVE_ID`, CAIR `PRIVATE_DRIVE_ID`, snapshot `PRIVATE_DRIVE_ID`.
- Derived review: SVG `PRIVATE_DRIVE_ID`, GLB `PRIVATE_DRIVE_ID`, STEP `PRIVATE_DRIVE_ID`, preview `PRIVATE_DRIVE_ID`.
- Semantic/graph: ontology `PRIVATE_DRIVE_ID`, JSON-LD `PRIVATE_DRIVE_ID`, nodes `PRIVATE_DRIVE_ID`, relationships `PRIVATE_DRIVE_ID`.
- Application outputs: Blender `.blend` `PRIVATE_DRIVE_ID`, FreeCAD `.FCStd` `PRIVATE_DRIVE_ID`, GIS exchange `PRIVATE_DRIVE_ID`.
- Iteration/validation: V001 manifest `PRIVATE_DRIVE_ID`, cross-format validation `PRIVATE_DRIVE_ID`, parse report `PRIVATE_DRIVE_ID`, validation status `PRIVATE_DRIVE_ID`.
- Project memory: context `PRIVATE_DRIVE_ID`, summary `PRIVATE_DRIVE_ID`, semantic index `PRIVATE_DRIVE_ID` and `PRIVATE_DRIVE_ID`.

The `AEC-2026-000003` project was then synchronized as a 33-file canonical
package. Key artifact IDs are:

- Raw/derived CAD: DXF `PRIVATE_DRIVE_ID`, SVG `PRIVATE_DRIVE_ID`.
- Manifest/CAIR: manifest `PRIVATE_DRIVE_ID`, CAIR `PRIVATE_DRIVE_ID`, latest snapshot `PRIVATE_DRIVE_ID`.
- Semantic outputs: ontology `PRIVATE_DRIVE_ID`, graph JSON-LD `PRIVATE_DRIVE_ID`, cross-format validation `PRIVATE_DRIVE_ID`, project memory `PRIVATE_DRIVE_ID`.
- Read-back confirmed all 33 files are present in their canonical subfolders and report `not_shared`.

Global registry files were also uploaded to `00_GLOBAL`:

- `global-manifest.json` → `PRIVATE_DRIVE_ID`
- `global-project-registry.jsonl` → `PRIVATE_DRIVE_ID`
- `global-artifact-registry.jsonl` → `PRIVATE_DRIVE_ID`
- `global-object-registry.jsonl` → `PRIVATE_DRIVE_ID`
- `global-relations.jsonl` → `PRIVATE_DRIVE_ID`
- `global-provenance.jsonl` → `PRIVATE_DRIVE_ID`
- `drive-repository.json` → `PRIVATE_DRIVE_ID`
- `cair-v0.1.schema.json` → `PRIVATE_DRIVE_ID`
- `cair-tables-v0.1.schema.json` → `PRIVATE_DRIVE_ID`

The Phase 7–10 additions were synchronized without changing existing Drive
IDs for project/global artifacts:

- Portable CAIR tables in project `03_CAIR`: `artifacts.jsonl` → `PRIVATE_DRIVE_ID`, `classifications.jsonl` → `PRIVATE_DRIVE_ID`, `geometry_index.jsonl` → `PRIVATE_DRIVE_ID`, `objects.jsonl` → `PRIVATE_DRIVE_ID`, `provenance.jsonl` → `PRIVATE_DRIVE_ID`, `relations.jsonl` → `PRIVATE_DRIVE_ID`, and `table-manifest.json` → `PRIVATE_DRIVE_ID`.
- Ontology alignments in global `02_ONTOLOGIES`: `aec-core.ttl` → `PRIVATE_DRIVE_ID`, `bot-alignment.ttl` → `PRIVATE_DRIVE_ID`, `omg-fog-alignment.ttl` → `PRIVATE_DRIVE_ID`, `geosparql-alignment.ttl` → `PRIVATE_DRIVE_ID`, `prov-o-alignment.ttl` → `PRIVATE_DRIVE_ID`, and `bsdd-alignment.ttl` → `PRIVATE_DRIVE_ID`.
- Ontology alignment manifest → `PRIVATE_DRIVE_ID`.
- Application exchange manifests: `freecad-cair-exchange.json` → `PRIVATE_DRIVE_ID`, `blender-cair-exchange.json` → `PRIVATE_DRIVE_ID`, and `qgis-cair-exchange.json` → `PRIVATE_DRIVE_ID`.
- Blender runtime outputs for CAIR snapshot `cair-20260901T053140Z-4d1fc3b2`: `.blend` → `PRIVATE_DRIVE_ID`, `.glb` → `PRIVATE_DRIVE_ID`, and visual QA PNG → `PRIVATE_DRIVE_ID`.
- FreeCAD runtime outputs for the same CAIR snapshot: `.FCStd` → `PRIVATE_DRIVE_ID`, and STEP wireframe → `PRIVATE_DRIVE_ID`.
- Latest derived validation, memory, and dashboard artifacts: global `repository-validation.json` → `PRIVATE_DRIVE_ID`, global `global-context.json` → `PRIVATE_DRIVE_ID`, project `AEC-2026-000004` `project-validation.json` → `PRIVATE_DRIVE_ID`, project `project-context.json` → `PRIVATE_DRIVE_ID`, dashboard `dashboard-data.json` → `PRIVATE_DRIVE_ID`, and dashboard `aec-dashboard.html` → `PRIVATE_DRIVE_ID`.
- Extended memory packages: global `project-summaries.parquet` → `PRIVATE_DRIVE_ID`, `lessons.parquet` → `PRIVATE_DRIVE_ID`, `strategies.parquet` → `PRIVATE_DRIVE_ID`, `design-patterns.parquet` → `PRIVATE_DRIVE_ID`, `ontology-index.parquet` → `PRIVATE_DRIVE_ID`, `global-object-registry.parquet` → `PRIVATE_DRIVE_ID`, `source-mapping.parquet` → `PRIVATE_DRIVE_ID`, and project memory `project-summary.md` → `PRIVATE_DRIVE_ID`, `semantic-index.parquet` → `PRIVATE_DRIVE_ID`, `active-design-state.json` → `PRIVATE_DRIVE_ID`, `ontology-summary.json` → `PRIVATE_DRIVE_ID`, and `artifact-index.json` → `PRIVATE_DRIVE_ID`.
- The non-empty JSONL companions were also added to global `09_AGENT_MEMORY`: `project-summaries.jsonl` → `PRIVATE_DRIVE_ID`, `global-object-registry.jsonl` → `PRIVATE_DRIVE_ID`, and `source-mapping.jsonl` → `PRIVATE_DRIVE_ID`. Empty optional JSONL companions remain represented by their Parquet counterparts.
- Read-back confirmed all new files are `not_shared`; no sharing or permission changes were made.
- The local `drive-repository.json` now records the verified Drive folder IDs for all 3 canonical projects, 000003/000004 read-back file counts, and the no-permission-change policy; the same file was updated in place at `PRIVATE_DRIVE_ID`.
- Drive-only cold-restore smoke was executed in an isolated temporary cache using the remote global registries plus project manifest, CAIR, geometry, ontology, graph, semantic Parquet, and artifact index. The latest local rebuild now contains 3 projects, 229 artifacts, 163 objects, 163 relations, and 163 provenance rows; the ODA project’s project-memory package and validation outputs are also synchronized in Drive.
- The local semantic runtime smoke also loaded the restored project Turtle with PyOxigraph and verified 95 quads; this is a rebuildable runtime check, not a replacement for the canonical ontology artifact.
- Operational documents in `99_SYSTEM`: `implementation-status.md` → `PRIVATE_DRIVE_ID`, `mcp-gateway.md` → `PRIVATE_DRIVE_ID`, `application-adapters.md` → `PRIVATE_DRIVE_ID`, `runtime-adapters.md` → `PRIVATE_DRIVE_ID`, and `drive-integration.md` → `PRIVATE_DRIVE_ID`.

The local repository now also produces rebuildable validation, agent-memory,
iteration, and dashboard artifacts. These are derived outputs: canonical CAIR
and raw source artifacts remain authoritative. The dashboard is eligible for
publication under the root `10_EXPORTS` folder after the target folder is
listed and an idempotent Drive record is established.

## Current portable-output contract

The local canonical repository now emits additional Drive-ready derived
artifacts without changing the authority model: project CAIR table packages
include properties, source mappings, honest application-reference mappings,
hyphenated interchange aliases, and `cair-manifest.json`; project and global
graphs include CSV and GraphML plus optional Parquet node/relationship files;
global registry JSON mirrors have optional Parquet companions. Iteration memory
rebuilds also populate the structured design-knowledge categories under
`07_DESIGN_KNOWLEDGE` (strategies, problems, solutions, design-moves,
precedents, lessons, metrics, failures, and design-patterns).

`rebuild_runtime_from_drive()` is the public cold-restore entry point. It
materializes remote artifacts into a disposable local cache, rebuilds global
indexes/runtime/memory, and validates the restored query path. Global artifacts
materialized from Drive are retained in later global-index rebuilds. With an
injected Drive client, file ingestion uploads the immutable source before
authoritative parsing and synchronizes derived outputs after success. Without
the client/root configuration, the implementation returns
`REQUIRES_CONFIGURATION` explicitly.

The 2026-09-02 portable-output synchronization was read back successfully:
`00_GLOBAL` contains 19 items, `03_KNOWLEDGE_GRAPH` contains the 5 global
GraphML/CSV/Parquet outputs, and `07_DESIGN_KNOWLEDGE` contains all 9 category
folders. Each canonical project now has 25 files in `03_CAIR/tables`, 8 files
in `05_GRAPH`, and 9 files in `13_AGENT_MEMORY`; the 000001 tables folder was
created during this pass at `PRIVATE_DRIVE_ID`. Global memory
contains 15 files after read-back, and validation/dashboard files were updated
in place. All checked items reported `not_shared`. Zero-byte optional JSONL
companions that the connector declined to upload remain represented by their
Parquet counterparts, as specified by the portable package contract.

## Boundary note

The current Python `GoogleDriveArtifactStore` remains connector-neutral and does not hard-code these IDs. The connected Drive workflow has now been read back after in-place updates: all 3 canonical project roots are represented, the ODA project lists 44 synchronized files, the 000003 project lists 33 synchronized files, all checked items report `not_shared`, and no permission changes were made. `MCPGateway` now accepts an injected Drive client for project/global synchronization, context download, and portable cold restore; the client contract records `google_drive_file_id`, `google_drive_folder_id`, SHA-256, MIME type, size, modified time, and visibility metadata while remaining idempotent on `(project_id, artifact_type, sha256)`. Without injection, the tools retain their explicit `REQUIRES_CONFIGURATION` status.
