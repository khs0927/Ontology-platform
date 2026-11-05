> **한국어 안내**: 이 폴더는 사용자 PC의 `C:\Users\USER\grokbot-mcp-bridge\`와 같은 내용입니다. 설치는 폴더를 그 위치로
> 복사하고 Node 18+로 실행합니다. `test-results\`(도구 전체 덤프)는 커밋하지 않습니다(`.gitignore`).
> 운영 규칙은 [`docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md`](../../docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md),
> 절차는 [`skills/local-cad-mcp-bridge/SKILL.md`](../../skills/local-cad-mcp-bridge/SKILL.md)에 있습니다.

# grokbot-mcp-bridge

A tiny, dependency-free Node script that lets the assistant use the MCP servers that are
configured on this PC (SketchUp, Revit, AutoCAD, ZWCAD, ...). It spawns one stdio MCP
server, does the MCP handshake, lists tools or calls one tool, prints JSON, and exits
(killing the whole child process tree).

Requires Node 18+ (tested with `C:\Program Files\nodejs\node.exe` v22).

## Config sources (read-only, never modified)

| order | source  | file                                                  |
|-------|---------|-------------------------------------------------------|
| 1     | cursor  | `%USERPROFILE%\.cursor\mcp.json` (`mcpServers`)        |
| 2     | claude  | `%APPDATA%\Claude\claude_desktop_config.json`          |
| 3     | codex   | `%USERPROFILE%\.codex\config.toml` (`[mcp_servers.*]`) |
| 4     | manual  | `horizun-revit` -> `%LOCALAPPDATA%\Programs\Horizun\**\horizun-mcp.exe` |

Every server has a qualified id `source:name` (e.g. `claude:sketchup`, `codex:power-cad`).
A bare name resolves to the first match in the order above. Codex `url = ...` entries are
listed as `remote` and are not spawned.

## Commands

```powershell
cd C:\Users\USER\grokbot-mcp-bridge
node mcp-call.mjs servers                       # merged list, secrets redacted
node mcp-call.mjs tools <server> [--timeout 30000] [--brief] [--verbose]
node mcp-call.mjs call  <server> <tool> [--args '<json>' | --args-file <path>] [--timeout 120000] [--verbose]
```

* `tools` prints `{server, serverInfo, protocolVersion, count, tools:[{name, description, inputSchema}]}`
  (`--brief` prints only tool names). `nextCursor` pagination is followed.
* `call` prints `{server, tool, result}`; exit code 3 if `result.isError` is true.
* On failure: exit code 1 and `{error, stage, server, exit, stderrTail, nonJsonStdout}` on stdout.
  `stage` is one of `resolve | spawn | initialize | tools/list | tools/call | args`.
* `--verbose` forwards the server's stderr (and notifications / non-JSON stdout lines) to stderr.
* From PowerShell, passing JSON with quotes in `--args` is fragile; prefer `--args-file args.json`.

Common options: `--cwd <dir>` / `--env KEY=VALUE` (override spawn cwd/env for this run),
`--out <file>` (write the UTF-8 JSON to a file, print only a short summary), `--ascii`
(escape non-ASCII as `\uXXXX`).

### PowerShell tips

* Set `[Console]::OutputEncoding = [Text.Encoding]::UTF8` before running node, otherwise
  PowerShell decodes node's UTF-8 output as CP949 and Korean text gets mangled. Or use
  `--out file.json` / `--ascii`.
* uvx/npx-launched servers (sketchup-mcp2, korean-law, kordoc) can take 40-90 s to start
  (package resolution + SketchUp connect retry); use `--timeout 120000` or rely on overrides.json.

### overrides.json (bridge-local)

Optional `overrides.json` next to the script patches a server's `cwd`, `env`, `args`,
`command` or default `timeout` without touching the user's MCP configs, e.g.
`{"claude:multiCAD-mcp": {"cwd": "C:\\CODE\\multiCAD-mcp"}}` (needed: its `-m src.server`
only works from the repo root).

## Behaviour details

* Transport: newline-delimited JSON-RPC over stdio (MCP stdio standard); also tolerates
  `Content-Length` framed replies. Non-JSON stdout lines are ignored.
* Handshake: `initialize` (protocolVersion `2025-06-18`, clientInfo `grokbot-bridge/1.0`,
  capabilities `{}`), then `notifications/initialized`. Server `ping` and `roots/list`
  requests are answered; other server->client requests get a -32601 error.
* Spawning: `shell:false`; commands are resolved via PATH/PATHEXT. `.cmd/.bat` shims (npx,
  etc.) are run through `cmd.exe /d /s /c`. Entries such as `cmd /c npx ...` are passed as is.
* Config `env` is merged over the current environment (plus `PYTHONUNBUFFERED=1` and
  `PYTHONIOENCODING=utf-8` unless set). Working dir = config `cwd`, else the config file's
  folder. Relative path-like args (e.g. `HWP\super_hwp_mcp\x.py`) are resolved against it.
* Cleanup: `taskkill /PID <pid> /T /F` on exit / timeout / Ctrl+C.
* Config files saved as CP949/EUC-KR (Korean Windows) are decoded automatically.

## Note on CAD servers

Most CAD servers list tools without the CAD app, but real tool calls need the app running
with its plugin/add-in (e.g. SketchUp Ruby TCP server on 127.0.0.1:9876, Revit add-in,
AutoCAD COM). Only call tools you intend to run: many of them modify the open model.
