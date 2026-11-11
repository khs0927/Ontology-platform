# 노출 API 키 폐기 런북 (공개 히스토리에 남은 키)

공개 저장소의 히스토리에 평문으로 커밋된 API 키가 **유효할 수 있습니다.** 키는 폐기(삭제)되기 전까지
그 키를 아는 사람이 아무 계정으로나 쓸 수 있고, 사용량이 비용으로 돌아옵니다. 이 런북은
"키가 아직 살아 있는가"를 **키 값을 노출하지 않고** 확인하고, 죽은 키를 확정·종결하는 절차를 담았습니다.

적용 대상 사례: `khs0927/HS-CAD`의 `opencode.json`에 2026-05-21부터 남아 있던 Google AI Studio 키
(2026-11-12 기준 이미 폐기됨 — 아래 "현재 상태" 참고).

---

## 0. 현재 상태 (2026-11-12 04:2x KST 검증)

| 항목 | 결과 |
|---|---|
| 공개 히스토리 전체(`git log --all`, 모든 파일)의 `AIza…` 패턴 | **1개** (`opencode.json@863f4be2`) |
| 그 키의 실사용 가능 여부 | **HTTP 400 `API_KEY_INVALID`** → 이미 폐기됨 |
| GitHub secret scanning 알림 | HS-CAD **알림 #1 = `resolved`** |
| 현재 `main`의 `opencode.json` | `{env:GOOGLE_GENERATIVE_AI_API_KEY}`만 참조 → 평문 키 없음 |
| 남아 있는 조치 | 새 키를 쓰는 PC의 환경변수 설정(아래 4단계). 키가 이미 죽었으므로 **긴급 아님** |

## 1. 유효성 확인 (키 값을 절대 출력하지 않기)

```powershell
# 1) 공개 저장소를 읽기 전용으로 받는다 (수정하지 않는다)
git clone --quiet https://github.com/<owner>/<repo>.git "$env:TEMP\<repo>-history"

# 2) 커밋된 파일에 남은 키 패턴의 개수만 센다 (값은 출력하지 않는다)
git -C "$env:TEMP\<repo>-history" log --all --format=%H -- opencode.json | ForEach-Object {
  git -C "$env:TEMP\<repo>-history" show "$($_):opencode.json" 2>$null
} | Select-String -Pattern 'AIza[0-9A-Za-z_\-]{20,}' -AllMatches |
  ForEach-Object { "found key pattern, length $($_.Matches[0].Value.Length)" }

# 3) 살아 있는지 확인한다 (키를 URL에 넣지만 응답 본문·헤더에는 키가 오가지 않는다)
$key = '<키를 여기서만 주입>'      # 클립보드/비밀관리자에서 읽어 변수에만 둔다
try {
  $r = Invoke-WebRequest "https://generativelanguage.googleapis.com/v1beta/models?key=$key" -UseBasicParsing
  "HTTP $($r.StatusCode) -> 아직 살아 있음: 즉시 폐기"
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  $body = $_.ErrorDetails.Message
  if ($code -eq 400 -and $body -match 'API_KEY_INVALID') { 'HTTP 400 API_KEY_INVALID -> 이미 폐기됨' }
  else { "HTTP $code -> 폐기 여부 판단 필요" }
}
```

> `AIza…`처럼 보이는 문자열을 이슈·PR·문서에 **붙여 넣지 마세요.** 확인은 위처럼 개수와 HTTP 상태만 읽습니다.

## 2. 폐기 (Google AI Studio)

1. [Google AI Studio → API Keys](https://aistudio.google.com/app/apikey) 접속.
2. 히스토리에 남은 키를 찾아 **Delete** 한다(키가 이미 죽었어도 레코드에서 지워야 재사용·재발을 막습니다).
3. **Disabled** 항목은 남아 있으면 Delete 없이 이름만 바꿔 "revoked (2026-11-12)"로 표시해도 됩니다.
4. 사용처를 모르면 **새 키를 먼저 발급**하고, 위 1단계에서 키가 죽었음을 확인한 뒤 옛 키를 삭제합니다.

## 3. GitHub 알림 종결

```powershell
# 저장소 → Settings → Code security → Secret scanning → 해당 알림 → "Revoked"/Closed
# API로 처리할 때:
gh api -X PATCH repos/<owner>/<repo>/secret-scanning/alerts/<number> -f state=resolved
gh api repos/<owner>/<repo>/secret-scanning/alerts --jq '.[]|"#\(.number) \(.state)"'
```

알림을 "Revoked"로 닫는 조건은 **키가 실제로 죽었음이 확인된 경우뿐**입니다. 살아 있는 키를 그냥 닫으면 사고가 조용히 이어집니다.

## 4. 새 키 배포 (환경변수만)

```powershell
[Environment]::SetEnvironmentVariable('GOOGLE_GENERATIVE_AI_API_KEY', (Read-Host -AsSecureString '새 키' | ConvertFrom-SecureString -AsPlainText), 'User')
```

- 파일·저장소·채팅·스크린샷·워크플로에 붙여 넣지 않습니다. `.env`도 커밋될 수 있으므로 주의합니다.
- 쓰지 않는 PC에서는 변수를 만들지 않습니다. 키는 "쓰는 곳에만" 존재해야 합니다.
- AI Studio에서 **사용량 알림(quota alert)**을 켜 두면, 키가 다시 새어 나가도 조기에 발견됩니다.

## 5. 히스토리 위생 판단

- **폐기가 1순위입니다.** 공개 히스토리에 키가 남은 채로는 "남은 사실"이 계속 사실이므로, 키를 죽이면 실질 위험은 사라집니다.
- 히스토리 리라이트(`git filter-repo` + 강제 푸시)는 **무료가 아니고 위험합니다**:
  - 이미 클론한 다른 사람·CI 캐시·포크에 키가 그대로 남습니다.
  - 이 저장소의 커밋 SHA를 다른 저장소가 참조하면(포크·의존성 핀) 리라이트가 무너집니다.
  - `AGENTS.md`는 공개 커밋의 noreply 이메일과 **로컬 복구 백업 유지**를 요구합니다.
- 따라서 **폐기 + 알림 종결 + 환경변수 전환**을 기본 조치로 삼고, 리라이트는 오너가 명시적으로 결정할 때만 합니다.

## 6. 점검 목록

- [ ] 공개 히스토리 전체에서 키 패턴이 몇 개 남았는지 확인(값 미출력)
- [ ] 각 키의 HTTP 상태 확인(`API_KEY_INVALID`면 폐기 완료)
- [ ] AI Studio에서 해당 키 Delete
- [ ] GitHub secret scanning 알림을 `resolved`로 종결
- [ ] `main`이 키를 평문으로 담지 않고 환경변수만 참조하는지 확인
- [ ] 쓰는 PC에 새 키를 환경변수로만 설정
- [ ] 사용량 알림 켜기
- [ ] 결과와 날짜를 `docs/ops/MAIN-PC-TODO.ko.md`에 기록
