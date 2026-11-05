# jev-mcp

Jev(TypeSafe System One)를 MCP 도구로 노출하는 의존성 없는 stdio MCP 서버입니다(Node 18+).
OpenCode, Antigravity, Claude Desktop/Code, Codex에 로컬 서버로 등록해 씁니다.
사용 규칙은 [`docs/mcp/JEV-TYPESAFE.ko.md`](../../docs/mcp/JEV-TYPESAFE.ko.md)를 따릅니다.

## 도구 (7)

| 도구 | 용도 | 필수 인자 |
|---|---|---|
| `jev_decide` | choice / noul / score 판단 | `state`, `question_spec` (예: `choice:allow\|deny\|ask`, `noul:...`, `score:low\|medium\|high`) |
| `jev_noul` | 명제가 참일 확률(0–1) | `state`, `statement` |
| `jev_verify` | 증거 대비 주장 검증 | `context`, `claim` |
| `jev_screen` | 안전 선별(allow / flag / deny) — 승인 아님 | `content` (`safety_policy` 선택) |
| `jev_classify` | 범주 분류 | `text`, `categories`(2개 이상) |
| `jev_rerank` | 후보 순위 | `criteria`, `candidates`(2개 이상) |
| `jev_tool_route` | 도구/전략 선택 | `objective`, `strategies`(2개 이상) |

## 동작

- 먼저 OpenCode Zen 무료 엔드포인트(`https://opencode.ai/zen/v1/systemone`, `jev-1.13-free`)를 키 없이 호출합니다.
- 실패하고 키가 있으면 TypeSafe 직접(`https://api.typesafe.ai/v1/systemone`, `jev-1.13.0`)으로 다시 호출합니다.
- 키 읽는 순서: 환경 변수 `JEV_API_KEY` → `JEV_ENV_FILE`(없으면 `~/aside-gpt/.env`)의 `JEV_API_KEY=` 줄. **코드에 키가 없습니다.**

## 등록 예

```powershell
claude mcp add --scope user jev -- node C:\CODE\Ontology-platform\tools\jev-mcp\jev-mcp-server.mjs
```

다른 클라이언트 형식은 [`docs/mcp/MCP-CLIENT-SYNC.ko.md`](../../docs/mcp/MCP-CLIENT-SYNC.ko.md) 참고.

## 빠른 확인 (네트워크 호출 없음)

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | node tools/jev-mcp/jev-mcp-server.mjs
```
