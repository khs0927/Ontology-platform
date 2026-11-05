# 비밀값 취급 지침 (MCP 설정)

이 저장소는 **공개 저장소**입니다. MCP 설정·스킬·도구를 다룰 때 다음을 지킵니다.
저장소 전체 규칙은 [`AGENTS.md`](../../AGENTS.md), [`SECURITY.md`](../../SECURITY.md)를 따릅니다.

## 금지

- API 키, OAuth 토큰, PAT, client secret, 쿠키, `.env` 파일, 개인 키를 커밋하지 않습니다.
- 사용자의 실제 설정 파일(`claude_desktop_config.json`, `.claude.json`, `config.toml`, `opencode.json`, `mcp_config.json`, `.cursor\mcp.json`)을 그대로 복사해 커밋하지 않습니다. 예시는 새로 작성하고 자리표시자를 씁니다.
- 도구 덤프(`test-results\`)나 로그를 검사 없이 커밋하지 않습니다. 서버 stderr에 토큰이 섞일 수 있습니다.
- 채팅·PR 본문·이슈에 키를 붙여 넣지 않습니다. 키를 화면에 출력하는 명령(`type .env`, `Get-Content config.toml` 전체 출력)을 피합니다.

## 권장

| 상황 | 방법 |
|---|---|
| stdio 서버가 키를 읽음 | 서버가 환경 변수를 읽게 하고 설정에는 키를 쓰지 않음 (예: jev는 `JEV_API_KEY` 또는 `JEV_ENV_FILE`) |
| OpenCode | `"environment": { "KEY": "{env:KEY}" }` 치환 |
| 원격 서버 | 가능한 한 OAuth 로그인(클라이언트가 토큰을 자체 저장소에 보관) |
| 문서 예시 | `<JEV_API_KEY>`, `<client-id>`, `<pid>` 같은 자리표시자 |
| 사용자 프로필 경로 | `C:\Users\USER\` 또는 `%USERPROFILE%`, `~` 로 표기 (개인 계정명 금지) |
| 출력 확인 | 브리지의 `servers` 명령은 이름에 key/token/secret/auth 등이 든 값과 `sk-`, `ghp_`, `github_pat_`, `hf_`, `xox?-`, `AIza` 패턴을 `<redacted>`로 가림. `--show-secrets`는 쓰지 않음 |

## 커밋 전 검사

```bash
python scripts/check_public_privacy.py
git diff --cached | grep -nE 'sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{20,}|github_pat_|hf_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|xox[abp]-|eyJ[A-Za-z0-9_-]{20,}\.|(TOKEN|SECRET|API_KEY)=[^<{$ ]' || echo "no secret-like strings"
```

발견하면 커밋에서 빼고, 이미 푸시했다면 해당 키를 즉시 폐기·재발급한 뒤 기록 정리를 사용자와 상의합니다(강제 푸시는 사용자 승인 필요).
