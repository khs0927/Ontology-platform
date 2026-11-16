# MCP 운영 지침 (Local CAD/AEC MCP)

로컬 CAD/AEC MCP 서버와 MCP 클라이언트 설정을 다루는 한국어 지침 모음입니다. 각 문서는 `##` 절 단위로
나뉘어 있어 GraphRAG 청크로 바로 쓸 수 있습니다.

| 문서 | 내용 |
|---|---|
| [LOCAL-CAD-MCP-OPERATIONS.ko.md](LOCAL-CAD-MCP-OPERATIONS.ko.md) | 앱/플러그인 전제, 포트 확인, 상태 확인 우선 규칙, 파괴적 도구 확인 규칙, 서버별 문제 해결 |
| [MCP-CLIENT-SYNC.ko.md](MCP-CLIENT-SYNC.ko.md) | Claude Desktop / Claude Code / Codex / OpenCode / Antigravity 설정 위치·형식·로그인·백업·검증 |
| [JEV-TYPESAFE.ko.md](JEV-TYPESAFE.ko.md) | Jev(TypeSafe System One) 사용 규칙과 jev MCP 도구 |
| [SECRETS.ko.md](SECRETS.ko.md) | 키·토큰 취급, 자리표시자, 커밋 전 검사 |
| [TOOL-CATALOG.ko.md](TOOL-CATALOG.ko.md) | 서버별 도구 수와 확인된 도구 이름(SketchUp 두 서버는 전체 목록) |
| [CHATGPT-MCP-E2E-CHECKLIST.ko.md](CHATGPT-MCP-E2E-CHECKLIST.ko.md) | Issue #71 G: 자동 MCP 검토 흐름 E2E 범위와 ChatGPT(iOS) OAuth 수동 체크리스트 |

지식 코어(법령·그래프)를 원격으로 제공하는 무상태 MCP 서버(`sion-mcp`)는 [`docs/MCP_SERVER.md`](../MCP_SERVER.md)를 참고합니다.

관련 위치:
- 스킬: [`skills/`](../../skills/README.md)
- 브리지 소스: [`tools/grokbot-mcp-bridge/`](../../tools/grokbot-mcp-bridge/README.md)
- jev MCP 서버: [`tools/jev-mcp/`](../../tools/jev-mcp/README.md)
- SketchUp 모델링 지침: [`docs/sketchup/`](../sketchup/MODELING-GUIDELINES.ko.md), [`docs/SKETCHUP_KNOWLEDGE.md`](../SKETCHUP_KNOWLEDGE.md)
