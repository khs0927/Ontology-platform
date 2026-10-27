# 01. MCP 설치·등록

## 서버 목록
| 이름 | 위치/명령 | 포트·연결 | 비고 |
|---|---|---|---|
| sketchup-mcp2 | SketchUp 확장(MCPforSketchUp) | TCP 9876 | SketchUp 확장 메뉴에서 서버 시작. 22개 도구 |
| hueflow | SketchUp 확장 | HTTP 8080 | `execute_ruby` 등 21개 |
| korean-law-router | `C:\CODE\korean-law-router\start-router.ps1` (fastmcp-proxy) | 127.0.0.1:8010 | 39개 도구 = korean-law 10 + korean-land 9 + permit-review 8 + archhub 12. 키는 doppler 경유 |
| site-pipeline | `C:\CODE\site-pipeline-mcp` (`.venv-pc`) | stdio | 19개 도구 (`.venv`는 읽기전용, 쓰지 말 것) |
| korean-land | `C:\CODE\korean-land-mcp` | stdio | 9개, V-World 기반 |
| korean-site-core | `C:\CODE\korean-site-core` (editable 설치) | 라이브러리 | `zoning_at`이 UQ111~114 4개 레이어 조회(PR #2) |
| permit-review | `C:\CODE\permit-review-mcp` | stdio | 8개, 라우터 자동 시작(PR #1) |
| open-meteo | cmer81/open-meteo-mcp | stdio | 17개, 키 없음(비상업) |
| gis-mcp | mahdin75/gis-mcp | stdio | 88개(좌표변환·버퍼) |
| osm-mcp-server | `C:\CODE\_vendor\osm-mcp-server-patched` | stdio | Overpass에 User-Agent 패치(없으면 406) |
| geospatial-osm | AiAgentKarl/geospatial-mcp-server | stdio | 인자 `mcp~=1.20` (`<`는 cmd 리다이렉트로 깨짐) |
| gdal-mcp | Wayfinder-Foundry | stdio | Python 3.12(fiona 휠) |
| aec-solar | `C:\CODE\aec-solar-mcp` (pvlib) | stdio | 태양 위치·그림자·일조 |
| qgis-mcp | nkarasiak (GPL-2.0) | 9879 | QGIS에서 플러그인 켜고 Start Server |
| blender-mcp | ahujasid | 9877 | 기본 9876은 sketchup-mcp2와 충돌 → 9877로 변경. `DISABLE_TELEMETRY=true` |
| bonsai-mcp | Show2Instruct | 9878 | Blender + Bonsai 확장 + Start Bridge |
| aec-assets-mcp | `C:\CODE\aec-assets-mcp` | stdio | 6개, SketchUp/BIM 자산 검색 |
| rvt-mcp | `%LOCALAPPDATA%\RvtMcp\rvt\server\current\rvt-mcp.exe` | named pipe `RvtMcp-<pid>` | 226개, Revit 2027 애드인 필요 |
| horizun-revit | `%LOCALAPPDATA%\Programs\Horizun\MCP\server\horizun-mcp.exe` | Horizun 애드인 | 111개. health가 30초 넘게 무응답인 때 있음 |
| power-cad | `C:\CODE\power-cad-mcp\dist\server\win-x64\power-cad-server.exe` | named pipe `powercad-a27-<pid>` | 26개, AutoCAD 2027 + PowerCad 플러그인 0.5.0 |

building-regulation-gateway는 MCP 서버가 아니라(FastAPI + MCP 클라이언트) 등록하지 않는다.

## 등록 위치(모두 같은 내용으로 맞춘다)
1. Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` → `mcpServers`에 추가 후 앱 재시작.
2. Claude CLI: `claude mcp add -s user <이름> -- <명령> [인자]` (사용자 범위). 확인 `claude mcp list` → Connected.
3. Cursor: `%USERPROFILE%\.cursor\mcp.json` → `mcpServers`.
4. 그록봇 브리지: `C:\Users\khs09\grokbot-mcp-bridge\overrides.json` (도구 목록을 덮어씀).
   - 점검: `node cad-check.cjs` (CAD 5종), `node mcp-call.mjs tools <서버> --brief`, `node mcp-call.mjs call <서버> <도구> --args '{}'`

키가 필요한 서버는 명령을 `doppler run --project mcp-agent-credentials --config dev --only-secrets <이름들> -- <명령>`으로 감싼다. 설정 JSON은 UTF-8(BOM 없음)으로 저장.

## 라우터(korean-law-router) 주의
- `uv tool install fastmcp-proxy --with fastapi==0.115.12` (새 FastAPI는 `add_event_handler` 제거됨).
- 자동 시작: 시작프로그램 폴더 바로가기 `korean-law-router.lnk` (작업 스케줄러 logon은 관리자 권한 필요).
- 필요한 비밀: LAW_OC, VWORLD_API_KEY, VWORLD_DOMAIN, ARCHHUB_SERVICE_KEY (값은 Doppler에만).
- V-World는 해외 IP를 막는다 → 실호출은 한국 IP인 이 PC에서만.

## 백업 이름
`*.bak-20261024c`(1차), `d`(라우터·OSS 1차), `e`(OSS 2차), `f`(CAD 등록) — overrides.json, claude_desktop_config.json, ~/.cursor/mcp.json, ~/.claude.json 옆.
