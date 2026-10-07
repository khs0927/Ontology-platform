# 다른 에이전트에게 일을 맡기는 가이드

이 문서는 **명령을 전달받은 에이전트가 기존 결정을 다시 논의하는 데 시간을 쓰지 않고, 작은 검증 가능한 변경을 완성하기 위한 인계서**다. 현재 저장소는 S00 뼈대 단계이며 G01~G08은 아직 구현 완료가 아니다.

## 먼저 전달할 정보

저장소: `https://github.com/khs0927/GOD-CAD` — 비공개이므로 작업 에이전트에게 기존 GitHub 접근 권한이 있어야 한다. 비밀 토큰을 프롬프트나 파일에 붙이지 않는다. 로컬 checkout에서 실행할 수 있으면 해당 경로를 지정한다.

사용자가 전달할 가장 짧은 시작 명령은 다음과 같다.

```text
GOD-CAD 저장소 https://github.com/khs0927/GOD-CAD 의 AGENTS.md를 읽고,
docs/agents/PROMPTS.ko.md의 G01만 구현해줘.
최종 방향은 docs/FINAL_CONCLUSION.ko.md를 따른다.
구현, 필요한 회귀 테스트, 문서와 JSON Schema 갱신까지 완료하고,
변경 브랜치에 커밋한 뒤 검토 가능한 PR을 만들어줘.
실행한 검사와 실행하지 못한 검사, 다음 작업의 시작점을 명확히 보고해줘.
```

Windows/ZWCAD 연동부터 맡길 때는 G01 대신 G02를 지정한다. 둘을 한 에이전트에 맡길 때는 G01 완료 후 G02 순서로 수행하게 한다. 실제 후속 에이전트를 자동 실행하는 설정은 이번 저장소에 포함하지 않는다.

## 공통 지시문

```text
너는 GOD-CAD의 담당 구현 에이전트다.
목표는 원본 CAD identity를 유지하는 이해·편집·검증 엔진이며,
이번 작업 범위는 아래의 작업 ID 하나다.

1. AGENTS.md, README.md, FINAL_CONCLUSION, ARCHITECTURE를 읽는다.
2. git status와 현재 구현·테스트를 확인하고 기존 변경을 보존한다.
3. 작업 ID의 선행 조건, 수정 범위, 완료 조건을 확인한다.
4. 현재 계약에 맞춰 구현하고, 필요한 실패 경로와 데이터 보존을 검증한다.
5. 계약을 바꾸면 버전·JSON Schema·예제·관련 소비자를 함께 고친다.
6. 근거 없는 인식 성공률, 완벽한 DWG 지원, 가짜 native 성공을 만들지 않는다.
7. 배정 범위 밖의 DB/클라우드/프런트엔드/모델 학습을 추가하지 않는다.
8. 테스트 결과·제약·다음 시작점을 남기고 커밋/PR로 인계한다.

배정 작업 ID: <G01~G08>
작업 명세: docs/agents/PROMPTS.ko.md의 해당 항목
추가 환경/도면/허용 범위: <있는 경우만 기입>
```

## 파일과 계약의 담당 경계

| 분야 | 주 담당 파일 | 충돌하기 쉬운 계약 |
| --- | --- | --- |
| DXF/기하 | `adapters/dxf.py`, `identity.py`, `topology.py`, parser fixtures | SourceRef, Geometry |
| Native CAD | `adapters/zwcad/`, `adapters/native.py`, native integration tests | SourceRef, native export/execution envelope |
| 의미/온톨로지 | `semantics.py`, `ontology/`, 의미 검토 문서 | SemanticObject, Evidence, Edge |
| 편집/검증 | `planner.py`, 후속 validation modules | Patch, PlanReport, 새 ExecutionReport |
| 통합/인터페이스 | `cli.py`, `pipeline.py`, 후속 MCP/UI | 각 모듈의 공개 함수·스키마 버전 |

`models.py`, `schemas/`, 의존성 lock은 여러 에이전트가 동시에 독립 변경하기 쉬우므로 작업 시작 때 한 작업에 소유권을 배정한다. 각 브랜치에서 계약 변경 필요성을 먼저 기록하고, 소비자 영향을 확인한 뒤 통합한다. 사용자가 병렬 작업을 요청한 경우에도 동일 파일을 각자 덮어쓰지 않도록 분리된 worktree를 사용한다.

## 순서와 검토

1. G01/G02의 읽기·식별 기반을 만든다.
2. G03에서 서로 다른 표현의 대응과 누락을 실제로 검증한다.
3. G04에서 후보를 실제 의미 객체로 묶고 근거·검토 상태를 만든다.
4. G05에서 아주 제한된 native 편집과 재열기 검증을 완성한다.
5. G06에서 벽·문·치수·해치별 편집 규칙을 구현한다.
6. G07에서 사용자가 검토할 인터페이스를 연결한다. G08은 각 단계와 함께 축적한다.

새 기능의 PR에는 최소 하나의 정상 사례와 해당 기능에서 실제로 발생할 수 있는 실패/미지원 사례를 포함한다. CAD 호스트가 필요한 PR은 코어 CI 통과와 호스트 통합 검증을 따로 보고한다.

## 완료 보고 양식

```text
작업 ID / 브랜치 / 커밋 / PR:
완료한 동작:
변경된 계약과 호환성:
수정한 주요 파일:
실행 명령과 결과:
원본·비대상 보존 증거:
미지원·실행하지 못한 검증:
후속 에이전트가 시작할 파일과 명령:
남은 작업 ID:
```

보고서에는 명령이 성공했다는 사실과 실제 기능 범위를 함께 쓴다. `NotImplementedError`, skip, native 미실행을 ‘통과’로 합산하지 않는다. 필요한 환경이 없으면 가능한 코어 작업을 마치고 해당 환경에서만 할 수 있는 검증을 구체적으로 남긴다.
