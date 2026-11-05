# 에이전트 스킬

에이전트(Grok Bot, Claude Code, Codex, OpenCode, Antigravity 등)가 불러 쓰는 절차형 스킬입니다.
각 폴더의 `SKILL.md`는 YAML frontmatter(`name`, `description`)로 시작합니다. 규칙의 근거는
[`docs/mcp/`](../docs/mcp/README.md) 지침에 있습니다.

| 스킬 | 언제 쓰나 |
|---|---|
| [local-cad-mcp-bridge](local-cad-mcp-bridge/SKILL.md) | Windows PC의 로컬 CAD/AEC MCP 서버를 브리지로 호출할 때 |
| [sketchup-mcp](sketchup-mcp/SKILL.md) | SketchUp을 `sketchup-mcp2` / `hueflow-sketchup`으로 조회·모델링할 때 |
| [mcp-client-sync](mcp-client-sync/SKILL.md) | MCP 서버 하나를 5개 클라이언트에 백업·검증과 함께 동기화할 때 |
| [jev-decision](jev-decision/SKILL.md) | 좁은 구조화 판단(choice/noul/score)을 Jev로 빠르게 내릴 때 |
| [typesafe-ai](typesafe-ai/SKILL.md) | 앱 기능에 TypeSafe System One 판단을 설계해 넣을 때 |

Revit(Horizun)·AutoCAD 전용 스킬은 아직 확인된 도구 이름이 적어 따로 만들지 않았습니다. 해당 내용은
[운영 지침](../docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md)의 서버 표와 문제 해결 절에 있습니다.
