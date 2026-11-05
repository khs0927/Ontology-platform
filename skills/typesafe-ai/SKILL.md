---
name: typesafe-ai
description: >-
  TypeSafe로 AI 기능을 만들 때 사용한다. TypeSafe는 작은 AI 판단 단위를 프로그래밍 프리미티브처럼
  쓰게 해 주며, Jev를 포함한 System One 모델은 자연어와 앱 상태를 타입 있는 판단과 확률로 바꾼다.
  기능에 "프로그래밍 가능한 상식"이 필요할 때, 앱에서 AI로 무엇이 가능할지 구상할 때, LLM
  프롬프트-파싱 단계를 구조화된 판단으로 바꿀 수 있을 때 쓴다.
---
# TypeSafe로 만들기

TypeSafe는 AI 판단 단위를 프로그래밍 프리미티브처럼 쓰게 합니다. 작은 판단을 조합해 더 큰 기능을 만듭니다.
**System One 모델**은 소프트웨어가 바로 소비할 수 있는 빠르고 좁은 판단을 돌려줍니다. **Jev**는 TypeSafe의
첫 System One 모델로, 자연어를 이해해 글이나 추론 설명 대신 타입 있는 답과 확률을 돌려줍니다. 흐름은 코드가
소유하고, 모델은 일반 코드가 의미 이해를 필요로 하는 곳에 상식을 공급합니다.
Jev 호출 자체의 규칙은 [`jev-decision`](../jev-decision/SKILL.md)과
[`docs/mcp/JEV-TYPESAFE.ko.md`](../../docs/mcp/JEV-TYPESAFE.ko.md)를 봅니다.

## 최신 문서 읽기

**TypeSafe 최신 문서가 기준입니다. 작업의 일부로 읽습니다.** 이 스킬은 방향만 주고, 개념·프롬프팅 지침·API 계약·
SDK 사용법·모델·한도·예제는 문서에 있습니다.

- [문서 인덱스](https://docs.typesafe.ai/llms.txt)에서 관련 페이지와 쿡북을 찾습니다. 사이트 전체가 아니라 필요한 부분만 읽습니다.
- 페이지 경로 뒤에 `.md`를 붙이면 Markdown이 나옵니다. 예: [how to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md).
  상대 링크는 `https://docs.typesafe.ai` 기준으로 풉니다.
- 통합 코드를 쓰기 전에 현재 API 또는 선택한 SDK 페이지와 관련 질문 설계 지침을 읽습니다. 새 흐름이면 가장 가까운 쿡북도 봅니다.
- 인덱스를 못 읽으면 아래 직접 링크나 사이트 탐색을 쓰고, 그래도 안 되면 로컬 문서나 설치된 SDK 타입을 쓰되
  그 한계를 밝히고 버전 의존 세부를 지어내지 않습니다.

| 작업 | 시작 문서 |
| --- | --- |
| 프로그래밍 모델 이해 | [System One](https://docs.typesafe.ai/concepts/system-one.md), [building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md) |
| 무엇을 만들지 탐색 | [Use-case map](https://docs.typesafe.ai/concepts/use-case-map.md), 인덱스의 관련 쿡북 |
| 입력과 질문 준비 | [State](https://docs.typesafe.ai/concepts/state.md), [primitives](https://docs.typesafe.ai/primitives.md) |
| 불확실성 처리 | [Confidence](https://docs.typesafe.ai/confidence.md) |
| API 코드 작성 | [HTTP API](https://docs.typesafe.ai/api.md), [Python SDK](https://docs.typesafe.ai/sdk/python.md), [JavaScript SDK](https://docs.typesafe.ai/sdk/javascript.md) |
| 예전 통합 갱신 | [Migration guide](https://docs.typesafe.ai/migrating-to-v1.md) |

## 쓸모 있는 형태 찾기

사용자가 원하는 동작(앱이 무엇을 보여 주고, 고르고, 바꾸고, 넘기는지)에서 시작해 필요한 판단으로 거슬러 갑니다.
알려진 규칙, 계산, 정확한 조회, 실행은 코드에 둡니다. 사용자의 스택과 범위를 지키고, 의미 이해가 도움이 되는 곳에만
TypeSafe를 넣습니다.

- **라우팅과 인자 채우기**: 요청이 핸들러와 타입 인자를 고르게 합니다. [function calling](https://docs.typesafe.ai/cookbooks/function_calling.md), [speculative fan-out](https://docs.typesafe.ai/patterns/fan-out.md).
- **생성 대신 선택**: 후보 값이나 원문 구간은 코드가 찾고, 판단으로 고른 뒤 복사·정규화합니다. [value extraction](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md), [structure recovery](https://docs.typesafe.ai/cookbooks/autoformat.md).
- **증거 찾기와 판단**: 후보를 가져와 질의 관련성을 비교하고 유용한 맥락을 고릅니다. [reranking](https://docs.typesafe.ai/cookbooks/rerank_typesafe.md), [hierarchical classification](https://docs.typesafe.ai/cookbooks/hierarchical_classification.md).
- **판단을 재사용 데이터로**: 차원별 점수를 한 번 매기고 가중치·임계값·순위는 코드나 UI가 바꿉니다. [composite scoring](https://docs.typesafe.ai/patterns/composite-scoring.md), [feature discovery](https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md).
- **검증과 상향**: 특정 주장이나 필드를 증거와 대조하고, 불확실하거나 실패한 경우 사람이나 추론 모델로 넘깁니다. [citation checks](https://docs.typesafe.ai/cookbooks/citation_check.md), [extraction cascades](https://docs.typesafe.ai/cookbooks/sde_cascade.md).
- **변하는 상태에 반응**: 코드가 목표와 관측을 유지하고 새 판단이 다음 단계를 이끕니다. 추론한 상태와 관측한 사실을 구분하고, 결과를 바뀐 상황에 적용하기 전에 신선도를 확인합니다.

이 저장소에서의 예: GraphRAG 검색 후보 재순위, SketchUp 정의의 객체 클래스 후보(`unverified`) 검토 우선순위,
korean-land 결과를 규정 평가 사실로 바꿀 때 근거 문장 선택.

## 판단 설계

| 필요 | 프리미티브 | 구분 |
| --- | --- | --- |
| 정해진 집합 중 하나 | [Choice](https://docs.typesafe.ai/primitives/choice.md) | 하나를 고름. 분포는 경쟁 선택지 비교 |
| 조건이 성립하는지 | [Noul](https://docs.typesafe.ai/primitives/noul.md) | 예일 확률. 별도 신뢰도 없음. 여러 라벨이면 라벨마다 하나 |
| 서술된 차원의 정도 | [Score](https://docs.typesafe.ai/primitives/score.md) | 순서 있는 단계의 확률 가중 위치 |

- 각 질문에 답하기 충분한 **state**(원문, 식별자, 관계, 정책, 현재 사실)를 줍니다. 여러 부분이면 이름 있는 JSON 필드를 씁니다.
- 판단은 **instructions**에, 가능한 답은 **criteria**에 둡니다. 질문 ID는 코드용이라 모델에 전달되지 않으므로 질문 안에 의미를 다 담습니다.
  중첩 state는 백틱 경로(`ticket.messages[0].text`)로 가리킵니다.
- 질문 하나에 좁고 일관된 판단 하나. 독립적으로 유용한 차원은 나누되 판단 대상의 관계는 깨지 않습니다.
- Score 단계는 구체적 상황을 서술하고 단독으로 이해되어야 합니다.
- 맞는 답이 없을 수 있으면 no-match를 넣습니다. 값 선택에서는 후보 누락이 없는지 확인합니다(빠진 값은 고를 수 없음).

## 조합과 검증

- **같은 state에 대한 독립 질문은 함께** 보냅니다(병렬, 서로의 답을 못 봄). 앞 답이 있어야 증거를 가져오거나 다음 선택지를
  정할 수 있을 때만 두 번째 요청을 합니다. 질문이 늘면 토큰도 늘므로 실제 비용과 지연을 측정합니다.
- 확률과 신뢰도로 동작을 정하되, 임계값은 사용자 데이터와 결과의 무게로 평가합니다. 신뢰도는 행동 허가가 아닙니다.
  Noul 0.5는 중간 강도가 아닙니다. 쓰지 않는 분기의 불확실성은 무시합니다.
- 정책은 명시적으로, 원시 판단은 재사용 가능하게 둡니다. 타입 출력은 인터페이스를 보장할 뿐 진실을 보장하지 않습니다.
  대상 도메인에서 성능을 검증합니다.
- 대표 사례와 앱 동작을 시험하고, 실패 시 state·질문·후보·답·조합·관측 결과를 확인해 증거 부족, 모델 오류, 코드 오류,
  서비스 장애를 구분합니다. 쿡북 임계값은 예시일 뿐입니다.
- 웹 앱에서는 API 키를 서버 쪽에만 둡니다([`docs/mcp/SECRETS.ko.md`](../../docs/mcp/SECRETS.ko.md)).
