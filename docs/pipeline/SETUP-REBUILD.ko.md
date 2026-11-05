# PC 재구축 절차 (Windows 메인 PC)

비밀값은 Doppler(`ai-api-keys`, `mcp-agent-credentials`)에만 둔다. 이 문서에는 이름만 쓴다.

## 1. 로컬 클론 경로 (기준)
- 코드 작업본: `C:\CODE\<repo>` (예: `C:\CODE\Ontology-platform`, `C:\CODE\site-pipeline-mcp`, `C:\CODE\power-cad-mcp`)
- Drive 동기화 폴더 안에서 직접 편집하지 않는다(`.CODE`는 백업/인수인계 계층).
- 온톨로지 프로젝트: `C:\CODE\Ontology\projects\AEC-2026-000007\`
- 클론: `gh repo clone khs0927/<repo> C:\CODE\<repo>` (REPOS.ko.md 목록)

## 2. MCP 설정 (6개 앱, 원본 = Claude Desktop 설정)
- Claude: `%APPDATA%\Claude\claude_desktop_config.json` (`mcpServers`)
- Codex: `%USERPROFILE%\.codex\config.toml` (`[mcp_servers.X]`, 경로는 작은따옴표 리터럴) — all-in-cad 비활성 상태 유지
- Antigravity: `%USERPROFILE%\.gemini\config\mcp_config.json` / Grok: `%USERPROFILE%\.grok\config.toml` / OpenCode: `%USERPROFILE%\.config\opencode\opencode.json` / Aside: `aside.settings`의 `mcp`
- 원칙: 빠진 항목만 추가, JSON 중복 키 금지, 추가 후 파싱 검증, 비밀 포함 서버는 복사 전 승인. 보관본은 값 `__FILL_IN__`.
- 이식용 소독 설정: Drive `MCP\` 폴더.

## 3. 포트 지도
| 서비스 | 포트 |
|---|---|
| SketchUp 플러그인(sketchup / sketchup-mcp2 / MCPforSketchUp) | 9876 |
| hueflow-sketchup-mcp 플러그인 | 8080 |
| QGIS MCP 플러그인 | 9877 |
| NVIDIA 로컬 프록시(baseUrl) | 127.0.0.1:18765 |

## 4. 실행 형태
- hueflow: `uvx hueflow-sketchup-mcp` (PyPI 0.1.1)
- sketchup-mcp2: `uvx --from <whl 경로> sketchup-mcp2` (v0.4.0 whl)
- site-pipeline: `uv sync` 후 `doppler run --project mcp-agent-credentials --config dev -- uv run site-pipeline-mcp` (VWORLD_API_KEY 등)
- power-cad-mcp: 저장소 README 기준 실행, helpers/all-in-cad 포함 빌드 확인
- Revit MCP: Revit 2027 애드인 로드 후 MCP 브리지 시작

## 5. SketchUp 플러그인 폴더 (현재 문제)
- Plugins 폴더가 `D:\C_Drive_Offload\SketchUp2025_Plugins` 정션, `Sketchup.extensions.count == 0` → Enscape/MCP 미로드 의심.
- 수정안(사용자 결정 대기): 정션 제거 후 실제 폴더로 복원하거나, 정션 대상 권한/경로 확인 → SketchUp 재시작 → Ruby 콘솔에서 `Sketchup.extensions.count` 재확인.

## 6. Claude CLI / NVIDIA / Jev
- Claude CLI: Pro 계정 로그인(`claude login`), 작도 호출 비용 0. API 키 사용 금지.
- NVIDIA NIM(무료): 키는 Doppler `ai-api-keys`, 로테이션은 `지침/NVIDIA_API_키_로테이션_지침.md`, 프록시 자동실행 `지침/NVIDIA_프록시_자동실행_u0_2026-10-21.md`. 버스트 3~4, 429 즉시 재시도 금지.
- Jev: user-jev MCP(jev_decide/jev_verify/jev_classify…), 핵심 결정은 반드시 판정 기록.

## 7. 적용 후 점검
1. 6개 앱 완전 재시작 2. SketchUp·QGIS·Revit 플러그인 서버 시작 3. `mcp-test.ps1` 4. 실패 항목만 수정.
