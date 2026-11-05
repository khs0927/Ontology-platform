# Mobile Sion graph snapshot: evidence-only MCP access

Status: **read-only interim integration; not a live canonical Sion deployment**.

## Purpose

Enable iPhone/ChatGPT users to inspect an existing Sion/AEC **derived snapshot** through a project-scoped, OAuth-authenticated MCP tool without running the local CAD workstation. Preserve the local Sion database and its Apache AGE graph as the source of truth. Do not represent a Drive graph export as current PostgreSQL/AGE state.

## Boundary and ownership

- Sion canonical graph: existing Sion runtime, PostgreSQL/Apache AGE and source-aware application logic; currently no remotely verified always-on runtime.
- Google Drive: durable source archive and derived node/relation CSV or Parquet exports. Treat these as versioned evidence, not a writable online knowledge graph.
- Activepieces: project-OAuth-protected, thin MCP read-only query of **fixed and reviewed** Drive snapshot files. The caller cannot select arbitrary Drive file IDs or rewrite a snapshot.
- ChatGPT: explicit authenticated MCP client only, with tool-level project allowlist.
- CAD applications: no GUI, COM or native write exposure through this boundary.

## Interim query contract

Tool: `sion_snapshot_query_readonly` (external private integration).

Inputs: `project_id` (allowlisted), `query` (plain text, bounded), optional `limit` (1–15) and `offset` (nonnegative integer). Fail closed before downloading any snapshot if the project is unknown or the parameters are invalid.

Result fields:

```json
{
  "project_id": "example-project",
  "query": "wall",
  "canonical": false,
  "read_only": true,
  "snapshot_modified_at": "source-snapshot-timestamp",
  "freshness_warning": "Derived snapshot; not live AGE",
  "totals": {
    "project_nodes": 0,
    "matched_nodes": 0,
    "matched_relations": 0
  },
  "offset": 0,
  "limit": 10,
  "next_offset": null,
  "nodes": [],
  "relationships": [],
  "provenance": {
    "nodes_drive_file_id": "source-qualified-ref",
    "edges_drive_file_id": "source-qualified-ref",
    "nodes_sha256": "64-character-content-hash",
    "edges_sha256": "64-character-content-hash"
  }
}
```

This example is a shape illustration, not an example of verified graph content. Full source and auth identifiers are kept in private operational configuration, **not this public repository**.

## Validation gates

1. Reject unknown project and invalid query/pagination **before** Drive access.
2. Retrieve fixed CSV files through user-scoped Drive OAuth; never leak OAuth credentials or user-wide browsing tools into the exposed query parameters.
3. Parse CSV respecting quoting, schema and size limits; reject malformed or excessively large rows.
4. Filter nodes by project before search; permit project-root `containsElement` edges only when the other endpoint is in the already-scoped node set. Reject cross-project edges.
5. Return bounded hits with a deterministic offset, exact matched totals and a `next_offset` rather than silently truncating results.
6. Hash the retrieved source bytes; include source modified time, schema and `canonical: false`, `read_only: true`.
7. Never offer a mutation/approval tool under this read-only name; regulation and compliance decisions remain advisory and require authorized review.
8. Verify GitHub CI and hosted MCP integration independently. A successful hosted flow test does not establish that the user's ChatGPT iPhone OAuth session has connected.

## Next steps toward full mobile ontology editing

To permit canonical relationship review or evidence writes, first verify a durable AGE-compatible Sion backend and migration/backups, per-user/project authorization, provenance and `expected_version` concurrency control, dry-run and review/approval audit events, and actual iOS MCP OAuth end-to-end execution. The existing supervision Neon database does **not** provide Apache AGE: it must not be silently substituted for Sion's canonical graph.

Existing Sion review and regulation boundaries remain unchanged. No deployment, database migration, Drive original mutation or CAD native write is authorized by this documentation.
