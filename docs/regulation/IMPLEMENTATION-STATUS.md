# 중첩규제 검토 구현 현황

기준일: 2026-11-05 · 범위: PR #101 (`archontos.review`, `/api/v1/regulation/reviews/*`)

이 문서는 코드에 들어간 것과 아직 사람이 확정해야 하는 것을 구분한다. 시험 자료는 모두 합성 자료이고, 실제 필지의 법적 결론이 아니다. 법적 허용 기능은 출시하지 않는다.

## 작업 묶음

| 작업 | 상태 | 코드 | 남은 것 |
|---|---|---|---|
| W01 현황/계약 동결 | 일부 | 이 문서 | 외부 저장소 pin 대조 |
| W02 범위/기준 사례 | 미착수 | 없음 | 관할·행위 확정, 법규 검토자가 검토한 기준 사례 |
| W03 공식자료 계약 | 미착수 | `sources.py`의 공급자 계약만 | 공식 CSV/API 샘플과 권한 확인 |
| W04 MCP 공급자 계약 | 일부 | `Provider`, `ProviderRegistry`, `FixtureProvider` | 실제 공급자 어댑터, 도구 스키마 pin |
| W05 사실/근거 모델 | 구현 | `model.py`, `facts.py` | 기준 사례로 재확인 |
| W06 버전/참조 해소 | 구현 | `legal.py` | 법제처 실자료 적재 |
| W07 후보/적용 계획 | 구현 | `candidates.py`, `applicability.py` | 공식 연결표와 조문 ID를 넣은 프로필 |
| W08 실행 상태 | 구현 | `runs.py` | 작업자 프로세스 분리, 재시도 예약 |
| W09 규칙 검토/평가 | 구현 | `rase.py`, `aggregate.py` | 검토된 규칙 작성 |
| W10 데이터 경계 | 일부 | `regulation_review.py` | ArchOntos DB의 평가 ID와 연결 |
| W11 GraphRAG | 일부 | `retrieval.py`, `sion_graphrag/scoped.py`, `citations.py` | LightRAG 실색인 연결, 격리 색인 검증 |
| W12 MCP/화면 | 일부 | REST, `/regulation` 화면 | `aec-mcp-router` 어댑터 |
| W13 변경영향 | 구현 | `impact.py` | 저장된 작업과 그래프의 자동 연결 |
| W14 운영/출시 | 미착수 | 없음 | 출시 지표, 복구, 라이선스 |

`구현`은 합성 자료의 처리 계약 시험을 통과했다는 뜻이다. 의미 검증을 끝냈다는 뜻이 아니다.

## 시나리오

S01–S32는 `packages/regulation/tests/test_review_scenarios.py`에 있다. 플랫폼 경로는 `tests/test_regulation_review_api.py`에서 확인한다. 이 시험은 처리 계약 시험이다. 로드맵의 의미 검증 사례와 독립 평가 사례는 아직 없으므로 3장의 출시 지표는 측정하지 않았다.

S31은 규제 경로 코드에 JEV 참조가 없음을 확인한다. S32는 이 패키지가 CAD·BIM 경로를 가져오지 않음을 확인한다. 라우터의 실제 동작은 어댑터가 들어온 뒤 시험해야 한다.

## 개발 전 확인 사항 D01–D10

| ID | 준비 상태 | 현재 구현의 기본값 | 필요한 결정 |
|---|---|---|---|
| D01 평가 소유권 | 미확정 | 실행 기록을 플랫폼 Document로 저장, `canonical:false` | ArchOntos 평가 ID 연결 방식 |
| D02 최초 관할·행위 | 미확정 | 없음. 출시 범위를 주장하지 않음 | 시군구 2곳과 행위 지정 |
| D03 공식 규제 API | 미확인 | 연결표 없음. 지정마다 `unsupported_source` 작업 생성 | 활용권한과 샘플 확인 |
| D04 토지 MCP 생산자 | 일부 | `korean-land-parcel-analysis/2` 해석만 구현 | 실제 생산자 pin |
| D05 법령 MCP 버전 | 미확인 | 어댑터 없음 | 도구 스키마·라이선스 확인 후 pin |
| D06 LightRAG 격리 | 일부 | 투영 범위 제한 구현, 색인 미연결 | `lightrag-hku==1.5.7` 실색인 시험 |
| D07 복잡 규칙 | 기본안 적용 | `SUPPORT_TABLE`: 비교, 선택, 예외 플래그. 나머지는 REVIEW | 지원 범위 확장 여부 |
| D08 규칙 검토 책임 | 미확정 | 작성자와 검토자 역할 분리 강제, 승인 규칙 없음 | 검토자와 기준 사례 지정 |
| D09 JEV 제거 범위 | 기본안 적용 | 새 REST 경로에 JEV 없음. 라우터 미변경 | 라우터 적용 시 범위 확인 |
| D10 과거 공간 자료 | 기본안 적용 | 시점을 정할 수 없는 사실은 unknown | 자료별 조회 가능 시점 확인 |

## 운영 설정

`SION_REGULATION_REVIEW_BUNDLE`은 조문·연결표·프로필·규칙을 담은 JSON 경로다(`archontos.review.bundle`). 없으면 카탈로그가 비고, 모든 체크리스트 항목이 미해결로 남는다. 기본 프로필은 조문 ID 없이 구조만 담고 있고 `reviewed:false`다.

실행 기록과 저장 작업은 기존 엔티티 표에 들어가므로 마이그레이션이 없다. 외부 공급자 executor는 아직 연결하지 않았다. 요청에 `requested_sources`를 넣어도 executor가 없으면 해당 노드는 `unsupported`로 끝나고 누락 장부에 남는다.
