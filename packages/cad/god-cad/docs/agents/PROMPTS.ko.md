# 작업별 에이전트 명령서

공통 조건은 루트 `AGENTS.md`와 `docs/AGENT_GUIDE.ko.md`다. 아래 각 항목 전체를 담당 에이전트에게 전달한다. 선행 조건이 충족되지 않은 작업을 완료된 것처럼 진행하지 않는다.

## G01 — DXF inventory와 좌표/식별 기반 확장

목표: 현재 top-level Model subset의 누락을 추적 가능한 inventory로 확장한다. DWG writer는 만들지 않는다.

담당: `src/god_cad/adapters/dxf.py`, `identity.py`, `models.py`, `schemas/`, `tests/`, `scripts/`.

작업:

1. layout 목록과 각 scope의 entity count를 기록한다. 지원하지 않는 공간은 조용히 제외하지 말고 coverage에 표시한다.
2. block definition과 INSERT occurrence를 분리한다. 중첩 insert path, 전체 transform, nonuniform scale, rotation, mirroring을 보존한다.
3. OCS→WCS, elevation, bulge 처리를 공식 ezdxf API와 합성 fixture로 구현한다. 보존할 수 없는 객체는 제한을 표시한다.
4. Xref와 proxy는 발견과 외부 참조 문맥을 기록한다. 자동 resolve/download 또는 Xref 쓰기는 하지 않는다.
5. 같은 block을 두 번 삽입한 경우 ID가 충돌하지 않도록 identity와 schema 버전을 확장한다.
6. 기존 CLI·planner가 새 모델을 잘못 수정하지 않도록 지원 capability를 갱신한다.

완료 조건: 단위/변환/중첩/미지원 fixture에서 누락이 설명되고, 서로 다른 인스턴스가 구분되고, 원본이 변하지 않으며, 기존 테스트·스키마 검사·데모가 통과한다. endpoint O(n²) 성능 한계와 개선 필요성도 기록한다.

## G02 — 실제 ZWCAD 환경 확인과 읽기 전용 추출

목표: 실제 호스트에서 사용할 수 있는 native extraction 경로를 확보한다.

담당: `adapters/zwcad/`, `src/god_cad/adapters/native.py`, `docs/environment/zwcad.md`, native fixture/test runner.

작업:

1. 설치된 ZWCAD 버전·아키텍처와 공식 SDK/런타임 호환성을 확인한다. SDK·제품 경로를 추정하지 않는다.
2. 해당 공식 예제로 최소 플러그인을 빌드·로드한다. SDK DLL은 로컬 참조하고 커밋하지 않는다.
3. capabilities와 read-only inventory 명령을 구현한다. handle, layer, CAD type, layout, block/xref context, units와 지원 상태를 반환한다.
4. JSON export를 Python 계약으로 읽을 수 있게 한다. 현재 Drawing은 DXF 전용이므로 형식 확장이 필요하면 버전·소비자를 함께 수정한다.
5. 합성 DWG를 열어 추출 전후 원본 무변경을 확인한다.

완료 조건: 빌드 로그·호스트 로드·명령 출력·원본 무변경을 재현할 수 있다. 환경이 없으면 조사와 인터페이스/fixture까지 완료하고 실제 build/load를 미실행으로 명시한다. SDK 없는 상황에 임의 COM UI 제어로 대체 성공을 주장하지 않는다.

## G03 — Native와 DXF의 원본 매핑 및 불일치 보고

선행: G01, G02. 목표: 서로 다른 표현이 같은 원본 객체를 가리키는지 검증한다.

담당: 새 `src/god_cad/fusion.py`, 매핑 계약, fixtures, 관련 docs.

작업:

1. 같은 원본 revision에서 생성한 native export와 DXF의 provenance를 기록한다.
2. native source ID와 DXF ID를 별도 유지한다. 확정 매핑, 후보 매핑, 모호함, 누락을 구분한다.
3. CAD type/layer/transform/geometry 등의 증거로 매핑한다. handle 일치만으로 확정하지 않는다.
4. CAD 종류별 개수·bounds·좌표·레이어·metadata coverage를 비교한다. 누락은 전체 객체 수와 함께 보고한다.
5. 독립적인 native 렌더 경로의 입력 revision과 렌더 설정을 manifest로 남긴다.

완료 조건: 같은 handle이 다른 문맥에 있는 사례, 변환에서 객체가 분해되는 사례, proxy 누락을 잘못 동일시하지 않는다. 매핑 미확정 대상은 native edit에 진입하지 못한다.

## G04 — 의미 객체 그룹과 공간 후보

선행: G01. 목표: 레이어 하나의 primitive 후보를 여러 기하가 묶인 의미 객체로 확장한다.

담당: `semantics.py`, `topology.py`, `ontology/`, 의미 객체/증거 계약과 tests.

작업:

1. 규칙 기반 baseline으로 평행선/폭/개구부·block metadata·문자 근거를 결합한다.
2. 의미 객체와 원본 entity의 N:M mapping 및 각 근거를 저장한다.
3. 후보/검토됨/확정/거부 상태를 설계한다. 사람이 확정할 수 있는 인터페이스 계약을 마련한다.
4. BOT/BEO/OMG/FOG에서 필요한 개념만 정확한 URI·버전 manifest로 연결한다.
5. RDF export와 SHACL이 필요한 경우 입력 JSON과 참조 무결성을 함께 검증한다. 미확정 후보를 rdf:type Wall로 자동 단정하지 않는다.
6. 방 경계와 문 연결의 작은 합성 fixture에서 정답·실패 사례를 측정한다. 모든 도면의 방 인식으로 일반화하지 않는다.

완료 조건: 레이어가 틀린 사례와 두 벽이 겹치는 사례를 포함해 근거·불확실성·원본 매핑을 검토할 수 있다. 모델 학습이나 Neo4j 도입은 별도 필요성이 확인될 때 계획한다.

## G05 — 제한된 native 편집과 저장 후 검증

선행: G03. 목표: 실제 CAD 호스트에서 고립된 지원 객체의 XY 이동 한 사이클을 완성한다.

담당: `adapters/zwcad/`, 별도 native 실행 계약, validator, integration tests.

작업:

1. v0.1 simulation 보고서와 별도의 production 실행 요청·응답을 설계한다. 필수 precondition과 승인 범위를 구체적 Patch에 연결한다.
2. document lock과 transaction 내에서 handle/context/현재 revision/지원 capability를 재검사한다.
3. 원본과 다른 경로의 테스트 복사본에서만 저장한다. 동일 patch 중복 실행과 출력 경로 충돌을 방지한다.
4. 저장 후 ZWCAD로 재열고 객체별 expected/actual 기하와 비대상 데이터, 원본 checksum을 비교한다.
5. 보고서의 검사 상태를 pass/fail/not_run/unsupported로 분리한다. 필수 미실행이 있으면 verified를 내지 않는다.
6. 실패 journal과 출력 격리 경로를 남긴다. 이미 저장된 transaction을 자동 rollback했다고 주장하지 않는다.

완료 조건: 정상 이동, stale revision, 잠긴 레이어, 없는 handle, save 실패, reopen 실패, 중복 요청을 호스트에서 검증한다. native 검증 결과 없이 `native_write_eligible=true`로 완성을 대신하지 않는다.

## G06 — 벽·문·치수·해치의 객체별 편집 규칙

선행: G04, G05. 목표: primitive 이동과 의미 편집을 명확히 구분해 한 가지 벽 편집을 완성한다.

담당: `planner.py`, 새 dependency/rule/constraint 모듈, native operation handlers.

작업:

1. `hosts`, `references`, `bounds`, `constrains` 등 관계에서 영향 대상을 계산한다.
2. 각 대상에 move/stretch/trim/recompute/rebuild 중 허용된 구체 연산을 배정한다.
3. 문 개구부·치수 참조·해치 경계·인접 벽 갱신을 구현하거나 불가능한 조합을 명시적으로 거부한다.
4. ‘오른쪽’, ‘넓혀라’처럼 다의적인 명령은 확정된 공간 좌표/대상 선택이 필요하다는 계약을 둔다.
5. 변경 전후 공간 폐합, 인접 관계, 실제 저장 데이터를 검사한다.

완료 조건: 합성 두 방/공유 벽/문/치수/해치 fixture에서 기대 결과와 비대상 보존을 확인한다. 관련 객체 전체에 동일 벡터를 적용하는 데모를 MOVE_WALL 완료로 보고하지 않는다.

## G07 — 에이전트 도구와 검토 화면

선행: G05, G06. 목표: 사용자 요청이 검토 가능한 계획과 검증된 결과로 이어지게 한다.

담당: 후속 MCP/API/UI 경계. 기존 코어의 계약을 재사용한다.

작업: read-only query, 후보 조회, plan, preview, 허용된 execute, verify 도구를 분리한다. 조회 범위를 제한하고 원본 provenance를 보여준다. LLM이 생성한 임의 코드를 실행하지 않는다. 실제 도면 외부 모델 전송은 사용자가 선택한 공급자/데이터 범위에서만 가능하게 한다.

완료 조건: 모호한 대상 선택, native 거부, 재검증 실패, 성공 결과가 각각 구별되어 사용자에게 표시된다. 실행되지 않은 단계를 성공 화면으로 대체하지 않는다.

## G08 — 평가 corpus와 회귀 기준

목표: 기능을 추가할 때마다 성능과 실패 범위를 재현 가능하게 측정한다.

담당: fixture manifest, benchmark runner, `docs/VALIDATION.ko.md`, 지원 매트릭스.

작업: 먼저 합성 corpus의 CAD type/변환/단위/관계별 정답을 정의한다. 실도면은 소유·사용 권한을 확인하고 비식별화/격리한다. 회사·프로젝트 단위로 평가 세트를 분리해 유사 도면 누출을 막는다. 학습 데이터·외부 연구 모델의 이용 조건은 채택 시 검토한다.

완료 조건: 추출 coverage, 의미/관계별 precision·recall, 편집 성공/거부, 예상 밖 변경, 처리 시간·메모리를 원본 및 실행 버전과 연결해 보고한다. 평균 하나로 미지원·실패 사례를 숨기지 않는다.
