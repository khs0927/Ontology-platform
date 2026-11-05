# jev / TypeSafe 사용 지침

TypeSafe의 System One 모델 **Jev**를 에이전트 작업에서 쓰는 규칙입니다. 관련 스킬:
[`skills/jev-decision`](../../skills/jev-decision/SKILL.md)(호출 절차),
[`skills/typesafe-ai`](../../skills/typesafe-ai/SKILL.md)(앱에 TypeSafe를 넣는 설계),
MCP 서버: [`tools/jev-mcp`](../../tools/jev-mcp/README.md).

## Jev는 무엇이고 무엇이 아닌가

- Jev는 자연어 상태(state)와 질문을 받아 **타입이 있는 판단과 확률**을 돌려주는 결정 함수입니다.
- 대화·코딩·글쓰기 모델이 아닙니다. 메인 에이전트나 대화형 서브에이전트 모델로 선택하지 않습니다.
- 추론, 도구 호출, 설명, 최종 답변은 일반 모델이 맡고, Jev는 좁은 판단 하나하나에만 씁니다.

## 모델과 엔드포인트

| 경로 | 엔드포인트 | 모델 ID | 키 |
|---|---|---|---|
| OpenCode Zen 무료(기한부) | `POST https://opencode.ai/zen/v1/systemone` | `jev-1.13-free` | 없음 또는 `OPENCODE_API_KEY` |
| TypeSafe 직접 | `POST https://api.typesafe.ai/v1/systemone` | `jev-1.13.0` | `TYPESAFE_API_KEY` (헬퍼) / `JEV_API_KEY` (MCP 서버) |

규칙:
1. 요청 본문에 항상 `model`을 명시합니다. `model` 없는 요청이나 스키마 모양의 대화 프롬프트는 유효한 Jev 호출이 아닙니다.
2. 무료 경로를 먼저 시도하고, 네트워크 오류·401/403/404/408/425/429/5xx(또는 본문 `type: server_error`)일 때만 TypeSafe 직접 경로로 넘어갑니다. 400/422 요청 오류는 요청을 고칩니다.
3. 다른 유료 모델로 몰래 대체하지 않습니다.
4. 키는 환경 변수나 로컬 `.env`에서만 읽고, 출력·로그·커밋하지 않습니다.

## 질문 설계

| 필요 | 프리미티브 | 주의 |
|---|---|---|
| 정해진 선택지 중 하나 | `choice` | 해당 없음 선택지를 넣음 |
| 명제가 참인지 | `noul` | 0–1 확률. 0.5는 "중간 강도"가 아니라 "예/아니오가 비슷" |
| 순서 있는 정도 | `score` | 각 단계는 구체적 상황으로 서술 |

- 독립된 판단은 질문 하나씩 나누고, 같은 state에 대한 질문은 한 요청에 함께 보냅니다(병렬 평가).
- Jev에게 코드 작성, 사실 검색, 계산, 날짜 비교, 개수 세기, 문장 생성을 시키지 않습니다.
- 임계값은 작업마다 명시하고, 불확실하거나 결과가 중대한 판단은 일반 모델이나 사람에게 넘깁니다.

## jev MCP 도구 (7개)

`jev_decide`, `jev_noul`, `jev_verify`, `jev_screen`, `jev_classify`, `jev_rerank`, `jev_tool_route`.

- `jev_screen`의 `allow`는 **승인이 아닙니다**. 파괴적 CAD 도구, 메시지 전송, 구매, 삭제, 게시 등 외부 영향이 있는 행동은 평소의 사용자 확인 절차를 그대로 따릅니다.
- `jev_verify`로 "작업 완료" 주장을 검증할 때는 실제 테스트 출력·도구 결과를 context로 넣습니다.
- 장기 임계값에 영향을 주는 판단은 응답의 모델 버전을 기록합니다.

## 출처와 라이선스

SDK·스킬·헬퍼 스크립트는 MIT 오픈소스이고, Jev 모델 자체는 TypeSafe의 비공개 호스팅 모델입니다.
공식 출처는 [`skills/jev-decision/references/SOURCES.md`](../../skills/jev-decision/references/SOURCES.md),
최신 API는 <https://docs.typesafe.ai/llms.txt>에서 확인합니다.
