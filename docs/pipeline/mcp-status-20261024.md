# MCP status — new PC DESKTOP-KTQHS1I (2026-10-24 KST)

Keys: Doppler `mcp-agent-credentials/dev` only (`doppler run --only-secrets ...`). No plaintext keys in any config.

## korean-law-router (127.0.0.1:8010)
- Runtime: `fastmcp-proxy` (Yurzs/fastmcp-mux) via `uv tool install ... --with fastapi==0.115.12` (newer FastAPI removed `add_event_handler`; old PC broke on Starlette 1.x `on_startup`).
- Config: `C:\CODE\korean-law-router\config.json` (UTF-8 without BOM, no secrets).
- Start: `C:\CODE\korean-law-router\start-router.ps1` → `doppler run --only-secrets LAW_OC,VWORLD_API_KEY,VWORLD_DOMAIN,ARCHHUB_SERVICE_KEY -- fastmcp-proxy start`.
- Autostart: Startup-folder shortcut `korean-law-router.lnk` (logon schtasks needs admin → access denied).
- Bridge auto-start: `ROUTER_START_SCRIPT` (permit-review-mcp PR #1).
- Backends / tools (39): korean-law 10 (global npm korean-law-mcp 4.15.6), korean-land 9 (C:\CODE\korean-land-mcp), permit-review 8, archhub 12 (public keyless remote https://mcp.gomdori.app/archhub via mcp-remote; local archhub-mcp source not on this PC).
- Live calls (PNU 3171034026115250000): search_law OK; resolve_parcel OK; permit-review collect_parcel OK (8 s); archhub find_region OK, building_profile upstream timeout (30 s on the remote server's data.go.kr call).

## V-World
- korean-site-core live: parcel, geocode, resolve_pnu, features_in_bbox, land_use_attrs, NED OK. `zoning_at` returned [] for non-urban parcels (queried LT_C_UQ111 only) → fixed, PR khs0927/korean-site-core#2 (UQ111–114).
- site-pipeline / korean-land per-tool calls: covered by a separate worker (branch fix/site-tool-calls-20261024).
- V-World blocks foreign IPs: live calls only from the Korean-IP PC.

## Registered servers (bridge overrides tools/list)
| server | status |
|---|---|
| sketchup-mcp2 | 22 tools |
| hueflow | 21 |
| site-pipeline | 19 (`.venv-pc`; old `.venv` is read-only) |
| korean-land | 9 |
| korean-law-router | 39 |
| permit-review | 8 |
| korean-law | 10 |
| aec-assets / threenative-assets / open-meteo / gdal-mcp / blender-mcp | 6 / 50 / 17 / 11 / 9 (asset worker) |
| osm-mcp-server, geospatial-osm | FAIL: path not found (asset worker's in-progress entries) |

Claude CLI: horizun-revit, rvt-mcp, power-cad, site-pipeline, korean-land, korean-law, korean-law-router, permit-review all Connected. power-cad also added to Cursor.
building-regulation-gateway: FastAPI service + MCP *client*, not an MCP server — not registered.

## Backups
`*.bak-20261024c` (first round), `*.bak-20261024d` (router round) next to overrides.json, claude_desktop_config.json, ~/.cursor/mcp.json, ~/.claude.json.
