---
name: mcp-client-sync
description: >-
  MCP 서버 하나(또는 여러 개)를 Claude Desktop, Claude Code, Codex, OpenCode,
  Antigravity 설정에 같은 내용으로 추가·수정·제거할 때 사용한다. 각 설정 파일을 백업하고,
  클라이언트 형식에 맞게 쓰고, 구문·목록·로그인·덮어쓰기 여부를 검증한다. Use when syncing
  an MCP server across Claude Desktop, Claude Code, Codex, OpenCode and Antigravity.
---
# MCP 클라이언트 동기화

설정 위치·형식·함정의 근거는 [`docs/mcp/MCP-CLIENT-SYNC.ko.md`](../../docs/mcp/MCP-CLIENT-SYNC.ko.md)에 있습니다.
비밀값 규칙은 [`docs/mcp/SECRETS.ko.md`](../../docs/mcp/SECRETS.ko.md)를 따릅니다.

## 입력 정리

먼저 서버 정의를 한 줄로 정리합니다.

| 항목 | 예 |
|---|---|
| 이름 | `jev` |
| 종류 | `stdio`(command + args + env) 또는 `remote`(url + 인증 방식) |
| 명령 | `node C:\CODE\Ontology-platform\tools\jev-mcp\jev-mcp-server.mjs` |
| 비밀값 | 환경 변수 이름만(`JEV_API_KEY`). 값은 받지도 쓰지도 않음 |
| 대상 클라이언트 | 기본 5개. Figma 원격은 Claude Code·Codex만, Gmail/Outlook/xAI Finance/Origin은 대상 아님 |

## 1. 백업 (편집 전에 반드시)

```powershell
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$files = @(
  "$env:APPDATA\Claude\claude_desktop_config.json",
  "$env:USERPROFILE\.claude.json",
  "$env:USERPROFILE\.codex\config.toml",
  "$env:USERPROFILE\.config\opencode\opencode.json",
  "$env:USERPROFILE\.gemini\antigravity\mcp_config.json"
)
foreach ($f in $files) { if (Test-Path $f) { Copy-Item $f "$f.bak-$ts"; "{0}  {1}" -f (Get-FileHash $f).Hash.Substring(0,12), $f } }
```

해시를 기록해 두고, 백업은 자동으로 지우지 않습니다.

## 2. 클라이언트별로 쓰기

| 클라이언트 | 방법 |
|---|---|
| Claude Code | CLI 우선: `claude mcp add --scope user <name> -- <command> <args...>` / 원격 `claude mcp add --scope user --transport http <name> <url>` |
| Codex | `config.toml`에 `[mcp_servers.<name>]` (`command`/`args` 또는 `url`) |
| OpenCode | `opencode.json`의 `mcp.<name>` (`"type": "local"`, `command` 배열 / `"type": "remote"`, `url`), 키는 `{env:NAME}` |
| Antigravity | `mcp_config.json`의 `mcpServers.<name>` (원격은 `serverUrl`) |
| Claude Desktop | `mcpServers.<name>` stdio만. 원격은 `npx -y mcp-remote <url>` |

규칙:
- Windows에서 `npx` 실행은 `cmd /c npx ...`로 씁니다(특히 Playwright).
- JSON 편집은 PowerShell `ConvertFrom-Json` → 수정 → `ConvertTo-Json -Depth 32` →
  `[IO.File]::WriteAllText($f, $text, (New-Object Text.UTF8Encoding($false)))` (BOM 없는 UTF-8).
  `Set-Content -Encoding UTF8`(PowerShell 5)은 BOM을 붙이므로 쓰지 않습니다.
- 한글 출력 전에 `[Console]::OutputEncoding = [Text.Encoding]::UTF8`.
- 기존 항목은 이름이 같을 때만 바꾸고, 다른 서버 항목은 건드리지 않습니다.
- 키 값을 설정에 직접 써야 하는 경우(Claude Desktop의 `env`)에도 사용자가 직접 넣게 하고, 에이전트는 자리표시자만 씁니다.

## 3. 검증

```powershell
foreach ($f in $files | Where-Object { $_ -like '*.json' -and (Test-Path $_) }) {
  node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'))" $f; if ($LASTEXITCODE) { Write-Warning "JSON 오류: $f" }
}
claude mcp list
codex mcp list
opencode mcp list
& "C:\Program Files\nodejs\node.exe" C:\Users\USER\grokbot-mcp-bridge\mcp-call.mjs servers
& "C:\Program Files\nodejs\node.exe" C:\Users\USER\grokbot-mcp-bridge\mcp-call.mjs tools <name> --brief
```

- stdio 서버는 브리지 `tools <name> --brief`로 실제 기동을 확인합니다(브리지는 cursor/claude/codex 설정을 읽음).
- Antigravity는 **MCP Servers > Manage > Refresh**로 목록을 확인합니다.

## 4. 로그인과 반영

| 클라이언트 | 동작 |
|---|---|
| Claude Desktop | 트레이에서 완전 종료 후 재실행 |
| Claude Code | `/mcp` → Authenticate |
| Codex | `codex mcp login <name>` |
| OpenCode | `opencode mcp auth <name>` |
| Antigravity | MCP Servers > Manage > Refresh / Authenticate |

OAuth 브라우저 로그인은 사용자가 직접 합니다. 에이전트가 토큰을 읽거나 옮기지 않습니다.
특수 사항: Hugging Face는 `https://huggingface.co/mcp?login`, Asana는 `https://mcp.asana.com/v2/mcp` + 직접 등록한
client ID/secret(예전 `/sse`는 2026-08-05 종료).

## 5. 덮어쓰기 재확인

Aside 에이전트 세션(CAD headless 테스트)이 `claude_desktop_config.json`을 덮어쓴 적이 있습니다.
1분 정도 뒤에 해시를 다시 비교하고, 바뀌었으면 백업과 비교해 원인을 사용자에게 알립니다.

## 6. 보고

클라이언트별로 "추가/변경/건너뜀(이유)", 백업 파일 경로, 검증 결과, 남은 로그인 단계를 표로 보고합니다.
복구 방법: `Copy-Item "<file>.bak-<ts>" "<file>" -Force` 후 클라이언트 재시작.
