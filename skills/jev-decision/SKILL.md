---
name: jev-decision
description: >-
  Jev 1.13으로 빠르고 타입이 있는 판단을 내릴 때 사용한다: 선택(choice), 참/거짓 확률(noul),
  점수·루브릭(score), 라우팅, 분류, 증거 확인, 순위, 신뢰도 기반 사람 검토. 판단을 좁은 구조화
  질문으로 표현할 수 있을 때 쓴다. Jev는 대화·코딩 모델이 아니며 메인 에이전트를 대신하지 않는다.
---
# Jev 판단 도우미

Jev는 대화 모델이 아니라 **특화된 판단 함수**로 다룹니다. 추론, 도구 사용, 설명, 최종 답변은 현재의 범용 모델이
맡고, Jev는 답이 "타입 있는 값 + 확률"인 범위가 정해진 판단에만 씁니다.
규칙의 근거: [`docs/mcp/JEV-TYPESAFE.ko.md`](../../docs/mcp/JEV-TYPESAFE.ko.md).
헬퍼: `scripts/jev.mjs`, 출처: `references/SOURCES.md`. MCP로 쓰려면 [`tools/jev-mcp`](../../tools/jev-mcp/README.md).

## 실행 경로

1. `zen-free/jev-1.13-free`를 메인 에이전트나 대화형 서브에이전트로 고르지 않습니다. Jev는 일반 답변이나 도구 호출을
   만들지 않으며, 대화 어댑터는 요청 스키마를 평가 없이 되돌려 줄 수 있습니다.
2. `node skills/jev-decision/scripts/jev.mjs <request.json>`을 씁니다. 헬퍼는 항상 OpenCode Zen 무료
   `jev-1.13-free` 엔드포인트를 먼저 시도합니다. `OPENCODE_API_KEY`가 있으면 그 요청의 인증에만 씁니다.
3. 무료 요청이 네트워크 오류이거나 재시도 가능한 응답(401, 403, 404, 408, 425, 429, 5xx, 또는 본문 `type`이
   `server_error`/`api_error`/`overloaded_error`)일 때만 TypeSafe 직접 경로 `jev-1.13.0`으로 재시도합니다.
   키는 `TYPESAFE_API_KEY`에서 읽습니다(Windows에서는 선택적으로 DPAPI 암호화 파일, 경로는 `JEV_TYPESAFE_DPAPI_FILE`).
   키를 출력하거나 로그에 남기지 않습니다.
4. 요청 본문에 모델을 명시합니다: `https://opencode.ai/zen/v1/systemone`에는 `jev-1.13-free`,
   `https://api.typesafe.ai/v1/systemone`에는 `jev-1.13.0`. 400/422(서버 오류 본문이 아닌 경우)는 요청 오류이므로
   경로를 바꾸지 말고 요청을 고칩니다. 다른 유료 모델로 몰래 대체하지 않습니다.
5. 직접 `/systemone` 요청에서 `model`을 빼지 않습니다. 스키마 모양의 대화 프롬프트나 `model` 없는 요청은 유효한
   Jev 호출이 아닙니다.

## 요청 만들기

독립된 판단마다 좁은 질문 하나. 그 판단에 필요한 증거만 state에 넣습니다.

- `choice`: 선택지 ID → 설명의 JSON 객체. 필요하면 "해당 없음"을 넣습니다.
- `noul`: 한 명제가 참인지. 0–1 확률이며 강도 점수가 아닙니다.
- `score`: 구체적인 루브릭 단계의 순서 있는 배열. 확률 가중 위치와 신뢰도를 돌려줍니다.

독립된 질문은 함께 보냅니다(같은 state에 대해 병렬 평가). Jev에게 코드 작성, 사실 검색, 계산, 날짜 비교,
개수 세기, 문장 생성을 시키지 않습니다.

## 안전한 해석

- Choice/Score 신뢰도는 분포의 집중도이지 전체 작업이 옳다는 증거가 아닙니다.
- Noul이 0.5 근처면 예/아니오 가능성이 비슷하다는 뜻이지 중간 강도가 아닙니다.
- 작업마다 명시한 임계값과 비교하고, 불확실하거나 중대한 판단은 범용 모델이나 사람에게 넘깁니다.
- 판단 결과를 전송·구매·삭제·게시 같은 외부 영향 행동의 허가로 쓰지 않습니다. CAD의 파괴적 도구와
  `eval_ruby`/`execute_ruby`도 마찬가지로 사용자 확인이 필요합니다.
- 장기 임계값에 영향을 주는 판단은 응답의 모델 버전을 기록합니다.
- 브라우저 작업이 이어지면 기존 탭을 유지하고 체크포인트를 남긴 뒤, 다시 붙어서 새 스냅숏을 찍고 행동합니다.
  Jev 결과만으로 브라우저 행동을 승인하지 않습니다.
- 401이나 422가 나오면 Jev 요청을 먼저 고치고, 바뀌지 않은 브라우저 상태에서 이어갑니다.

## 직접 호출 예

```json
{
  "state": "결제 실패가 3일째 계속되어 판매를 잃고 있습니다. 지금 asap로 도와주세요.",
  "questions": {
    "is_urgent": { "type": "noul", "instructions": "이 메시지는 긴급함 또는 시간 민감성을 나타내는가?" },
    "department": {
      "type": "choice",
      "instructions": "어느 팀이 처리해야 하는가?",
      "criteria": { "billing": "결제와 구독 문제", "technical": "버그와 연동 문제", "other": "위 항목에 해당하지 않음" }
    }
  }
}
```

```bash
node skills/jev-decision/scripts/jev.mjs /tmp/jev-request.json
```

키가 없거나 OpenCode 키만 있으면 `jev-1.13-free`를 씁니다. 무료 모델은 기한부라 사라질 수 있으며, 그때도 유료 모델로
몰래 대체하지 않습니다.

## CAD 작업에서의 예

- `choice`: 사용자 요청이 `read_only` / `modify_geometry` / `delete` / `run_code` 중 무엇인지 분류 → `delete`·`run_code`면 확인 절차.
- `noul`: "도구 결과가 요청한 객체(ID 목록)를 모두 포함한다"를 결과 JSON을 state로 넣어 확인.
- `score`: 서버 상태 로그를 보고 `down` / `degraded` / `ok` 판정 → `down`이면 대체 서버 안내.

## 출처 정책

SDK, 헬퍼 스킬, 스크립트는 MIT 오픈소스입니다. Jev 자체는 TypeSafe의 비공개 호스팅 소프트웨어이며 가중치나 추론
코드는 공개되지 않았습니다. 공식 출처와 경계는 `references/SOURCES.md`를 봅니다.
