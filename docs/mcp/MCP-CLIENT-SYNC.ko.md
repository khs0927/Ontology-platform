# MCP 클라이언트 동기화 지침

같은 MCP 서버 집합을 Claude Desktop, Claude Code, Codex, OpenCode, Antigravity에 맞춰 넣고 유지하는 규칙입니다.
절차형 스킬은 [`skills/mcp-client-sync`](../../skills/mcp-client-sync/SKILL.md)에 있습니다.
모든 예시의 키·토큰은 자리표시자(`<...>`)입니다. 실제 값은 저장소에 절대 넣지 않습니다([비밀값 취급](SECRETS.ko.md)).

## 동기화 대상 서버

| 구분 | 서버 | 비고 |
|---|---|---|
| 원격(Grok Bot 커넥터와 같은 것) | Supabase, Vercel, Context7, Hugging Face, Figma, Exa, Playwright, jev, autodesk-product-help, GitHub, Asana | Playwright·jev는 로컬 stdio |
| 로컬 CAD/AEC | [운영 지침](LOCAL-CAD-MCP-OPERATIONS.ko.md)의 서버 표 | Windows 전용 앱 필요 |
| 옮길 수 없음 | Gmail, Outlook, xAI Finance, Origin | Grok 전용 커넥터. 다른 클라이언트로 동기화하지 않음 |

원격 엔드포인트(작성 시점 기준, 바뀔 수 있으니 각 공식 문서로 다시 확인):

| 서버 | URL | 인증 |
|---|---|---|
| autodesk-product-help | `https://developer.api.autodesk.com/knowledge/public/v1/mcp` | 공개 |
| Hugging Face | `https://huggingface.co/mcp?login` | OAuth (`?login`을 붙여야 브라우저 로그인) |
| Asana | `https://mcp.asana.com/v2/mcp` | OAuth, **직접 등록한 client ID/secret 필요**. 예전 `/sse` 엔드포인트는 2026-08-05에 종료 |
| Figma | `https://mcp.figma.com/mcp` | OAuth, **승인된 클라이언트(Claude Code, Codex)에서만 동작** |
| Context7 | `https://mcp.context7.com/mcp` | 선택적 API 키 |
| Supabase | `https://mcp.supabase.com/mcp` | OAuth |
| Vercel | `https://mcp.vercel.com` | OAuth |
| Exa | `https://mcp.exa.ai/mcp` | API 키 또는 OAuth |
| GitHub | `https://api.githubcopilot.com/mcp/` | OAuth 또는 PAT(환경 변수) |
| Playwright | 로컬: `npx -y @playwright/mcp@latest` | Windows에서는 `cmd /c npx ...` |
| jev | 로컬: `node <repo>\tools\jev-mcp\jev-mcp-server.mjs` | `JEV_API_KEY`는 환경 변수 또는 `.env` |

## 클라이언트별 설정 위치와 형식

예시의 `C:\CODE\Ontology-platform`은 이 저장소를 받은 위치의 예입니다. 실제 경로로 바꿉니다.

| 클라이언트 | 설정 파일 (Windows) | 루트 키 | 원격 서버 표기 |
|---|---|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` | stdio만 → `npx -y mcp-remote <url>` |
| Claude Code | `~\.claude.json` (사용자 범위) | `mcpServers` | `claude mcp add --scope user --transport http <name> <url>` |
| Codex | `~\.codex\config.toml` | `[mcp_servers.<name>]` | `url = "<url>"` |
| OpenCode | `~\.config\opencode\opencode.json` | `mcp` | `"type": "remote", "url": "<url>"` |
| Antigravity | `~\.gemini\antigravity\mcp_config.json` | `mcpServers` | `"serverUrl": "<url>"` |

### Claude Desktop

원격 서버는 `mcp-remote`로 감쌉니다.

```json
{
  "mcpServers": {
    "playwright": { "command": "cmd", "args": ["/c", "npx", "-y", "@playwright/mcp@latest"] },
    "jev": {
      "command": "node",
      "args": ["C:\\CODE\\Ontology-platform\\tools\\jev-mcp\\jev-mcp-server.mjs"]
    },
    "huggingface": { "command": "npx", "args": ["-y", "mcp-remote", "https://huggingface.co/mcp?login"] },
    "autodesk-product-help": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://developer.api.autodesk.com/knowledge/public/v1/mcp"]
    }
  }
}
```

- `jev`는 키를 설정에 쓰지 않고 사용자 환경 변수 `JEV_API_KEY`나 `.env`(`JEV_ENV_FILE`)에서 읽게 합니다.
- 반영: 트레이 아이콘에서 Claude Desktop을 **완전히 종료한 뒤 다시 실행**합니다(창 닫기만으로는 안 됨).

### Claude Code

```powershell
claude mcp add --scope user playwright -- cmd /c npx -y @playwright/mcp@latest
claude mcp add --scope user jev -- node C:\CODE\Ontology-platform\tools\jev-mcp\jev-mcp-server.mjs
claude mcp add --scope user --transport http huggingface "https://huggingface.co/mcp?login"
claude mcp add --scope user --transport http figma https://mcp.figma.com/mcp
claude mcp list
```

- 결과는 `~\.claude.json`의 `mcpServers`에 기록됩니다(`"type": "stdio" | "http"`).
- 로그인: Claude Code 안에서 `/mcp` → 서버 선택 → Authenticate.

### Codex

```toml
[mcp_servers.playwright]
command = "cmd"
args = ["/c", "npx", "-y", "@playwright/mcp@latest"]

[mcp_servers.jev]
command = "node"
args = ['C:\CODE\Ontology-platform\tools\jev-mcp\jev-mcp-server.mjs']

[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"

[mcp_servers.power-cad]
command = "<power-cad 실행 명령>"
args = ["--target", "autocad-2027-<pid>"]   # AutoCAD 재시작 후 갱신
```

- TOML 문자열에서 Windows 경로는 작은따옴표(리터럴)로 쓰거나 `\\`로 이스케이프합니다.
- 로그인: `codex mcp login <name>`. 확인: `codex mcp list`.

### OpenCode

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "playwright": { "type": "local", "command": ["cmd", "/c", "npx", "-y", "@playwright/mcp@latest"], "enabled": true },
    "jev": {
      "type": "local",
      "command": ["node", "C:\\CODE\\Ontology-platform\\tools\\jev-mcp\\jev-mcp-server.mjs"],
      "environment": { "JEV_API_KEY": "{env:JEV_API_KEY}" },
      "enabled": true
    },
    "huggingface": { "type": "remote", "url": "https://huggingface.co/mcp?login", "enabled": true }
  }
}
```

- `{env:NAME}` 치환으로 키를 파일 밖에 둡니다.
- 로그인: `opencode mcp auth <name>`. 확인: `opencode mcp list`.

### Antigravity

```json
{
  "mcpServers": {
    "playwright": { "command": "cmd", "args": ["/c", "npx", "-y", "@playwright/mcp@latest"] },
    "jev": { "command": "node", "args": ["C:\\CODE\\Ontology-platform\\tools\\jev-mcp\\jev-mcp-server.mjs"] },
    "huggingface": { "serverUrl": "https://huggingface.co/mcp?login" }
  }
}
```

- 원격 서버는 `url`이 아니라 `serverUrl`입니다.
- 로그인/반영: **MCP Servers > Manage > Refresh**, 필요하면 **Authenticate**.

## 알려진 함정

| 함정 | 대응 |
|---|---|
| Windows에서 Playwright가 안 뜸 | `npx`는 `.cmd` shim이라 `cmd /c npx ...`로 실행 |
| Figma 원격이 Claude Desktop/OpenCode/Antigravity에서 거부 | Figma는 승인된 클라이언트(Claude Code, Codex)만 허용. 나머지에는 넣지 않음 |
| Asana `/sse` 404 | 2026-08-05 종료. `https://mcp.asana.com/v2/mcp` + 직접 등록한 client ID/secret |
| Hugging Face 로그인 창이 안 뜸 | URL에 `?login` |
| `claude_desktop_config.json`이 되돌아감 | 다른 프로세스(Aside 에이전트 세션의 CAD headless 테스트)가 덮어쓴 적이 있음. 편집 후 다시 확인 |
| 한글 깨짐/BOM | PowerShell 5의 `Set-Content -Encoding UTF8`은 BOM을 붙임. `[IO.File]::WriteAllText`+BOM 없는 UTF-8 사용 |
| PowerShell 5 `ConvertTo-Json`이 중첩을 잘라냄 | 기본 깊이 2. 항상 `-Depth 32` |

## 백업과 검증 절차

모든 편집은 **백업 → 편집 → 구문 검증 → 클라이언트 반영 → 재확인** 순서입니다.

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ts  = Get-Date -Format 'yyyyMMdd-HHmmss'
$cfg = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'

# 1) 백업 (덮어쓰지 않는 타임스탬프 사본)
Copy-Item $cfg "$cfg.bak-$ts"
$before = (Get-FileHash $cfg -Algorithm SHA256).Hash

# 2) 편집: 읽기 → 객체 수정 → BOM 없는 UTF-8로 쓰기
$j = [IO.File]::ReadAllText($cfg) | ConvertFrom-Json
# 예: $j.mcpServers | Add-Member -NotePropertyName 'jev' -NotePropertyValue ([pscustomobject]@{ command='node'; args=@('C:\CODE\Ontology-platform\tools\jev-mcp\jev-mcp-server.mjs') }) -Force
$text = $j | ConvertTo-Json -Depth 32
[IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding($false)))
$after = (Get-FileHash $cfg -Algorithm SHA256).Hash

# 3) 구문 검증
node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')); console.log('json ok')" $cfg

# 4) 서버 목록 확인 (브리지는 cursor/claude/codex 설정을 모두 읽고 비밀값을 가림)
& "C:\Program Files\nodejs\node.exe" C:\Users\USER\grokbot-mcp-bridge\mcp-call.mjs servers

# 5) 재확인: 잠시 뒤 다른 프로세스가 덮어쓰지 않았는지
Start-Sleep 60
if ((Get-FileHash $cfg -Algorithm SHA256).Hash -ne $after) { Write-Warning '설정이 다른 프로세스에 의해 바뀌었습니다. 백업과 비교하세요.' }
```

검증 체크리스트:
- [ ] 편집한 파일마다 `*.bak-<타임스탬프>` 백업이 있다.
- [ ] JSON은 `JSON.parse`, TOML은 `codex mcp list`(또는 브리지 `servers`)로 읽힌다.
- [ ] 클라이언트별 목록 명령: `claude mcp list`, `codex mcp list`, `opencode mcp list`, Antigravity Manage 화면.
- [ ] 로컬 stdio 서버는 브리지로 `tools <name> --brief`가 성공한다.
- [ ] OAuth 서버는 각 클라이언트의 로그인 절차를 마쳤다.
- [ ] 설정 파일에 평문 키가 새로 들어가지 않았다(가능하면 환경 변수 참조).
- [ ] 1분 뒤 해시가 그대로다.

복구: `Copy-Item "$cfg.bak-<타임스탬프>" $cfg -Force` 후 클라이언트를 다시 시작합니다. 백업 파일은 자동으로 지우지 않습니다.

## 클라이언트별 로그인 요약

| 클라이언트 | 로그인/새로고침 |
|---|---|
| Claude Desktop | 트레이에서 완전 종료 후 재실행. 원격은 `mcp-remote`가 브라우저 OAuth를 띄움 |
| Claude Code | `/mcp` |
| Codex | `codex mcp login <name>` |
| OpenCode | `opencode mcp auth <name>` |
| Antigravity | MCP Servers > Manage > Refresh / Authenticate |
