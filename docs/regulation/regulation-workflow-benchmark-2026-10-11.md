# 처리과정 벤치마킹과 설계 결정

조사일: 2026-10-11. 이번 요청에서 Exa로 6개 추가 조사 방향, 검색 결과 30건을 요청·검토했다. 중복을 포함하며 30개 시스템을 실사했다는 의미는 아니다. GitHub 플러그인으로 10개 파일의 일부 구간을 읽고 처리 흐름을 확인했다. 앞선 조사와 합쳐 Exa 검색 범위는 16개 방향·110건이다. 검색 건수는 품질의 증거가 아니므로 아래에 실제 채택 근거와 제한을 적는다. 설치·실행·외부 API 정확성 검증은 하지 않았다.

## 1. 토지 MCP: 공간 조회와 후속 조회 제안

원본: [analyze_parcel.ts](https://github.com/UrbanWatcherKr/korean-land-mcp/blob/main/src/tools/analyze_parcel.ts), [overlays.ts](https://github.com/UrbanWatcherKr/korean-land-mcp/blob/main/src/lib/overlays.ts).

확인한 처리 순서:

1. 주소를 필지로 해소하고 지번을 파싱한다.
2. 경계 WKT가 있으면 polygon 조회, 없으면 point 조회를 선택한다.
3. 용도지역·지구·구역, 지구단위계획, 시설, 다른 법률상 지정, 건물 조회를 병렬로 수행한다.
4. 공급자 속성의 여러 이름/코드 키를 공통 hit 형식으로 정리한다.
5. 지정 후보에 수동 governing_law/priority 플래그를 붙인다.
6. 결과·precision·layer_errors와 다음 법령 조회 제안을 반환한다.

채택: 필지 확정→여러 레이어 조회→공통 사실→후속 법령 조회의 순서, 레이어별 실패 노출, 좌표/정밀도 구분.

수정할 설계: 코드의 queryOverlays는 기본 layer size 5를 사용한다. 반환 hit만으로 해당 레이어의 모든 중첩을 확보했다고 가정하지 않고 페이지/상한 확인을 추가한다. 건물 조회에서 VWorldError가 빈 배열로 바뀌는 부분도 건물 없음과 수집 실패를 구분하도록 어댑터 설계가 필요하다. first zone에서 나온 next_steps만으로 여러 용도지역의 후속 법령 검토를 끝내지 않는다. 수동 우선위임 플래그는 후보 힌트로만 취급한다.

플랫폼에는 이미 토지 MCP 브리지와 별도의 pinned fork가 있다. 벤치마킹한 UrbanWatcherKr upstream와 현재 계약 공급자를 동일 저장소로 간주하지 않는다. 계약 대조 후 기존 브리지에 필요한 정보만 추가한다.

## 2. 법령 MCP: 작업 유형별 조사 체인

원본: [legal-research.ts](https://github.com/chrisryugj/korean-law-mcp/blob/main/src/tools/legal-research.ts), [applicable-law.ts](https://github.com/chrisryugj/korean-law-mcp/blob/main/src/tools/applicable-law.ts), [chain-deadline.ts](https://github.com/chrisryugj/korean-law-mcp/blob/main/src/tools/chain-deadline.ts).

확인한 흐름:

- 작업 유형을 법체계·조례비교·절차·시점 비교 등으로 나누고 적절한 체인에 전달한다.
- 적용 법령 조회는 연혁에서 기준시점 버전을 찾고 해당 조문과 현재 조문을 비교하며 부칙의 적용례·경과조치를 추출한다.
- 요청 조문번호와 실제 응답 조문번호를 대조한다. 잘못된 응답의 첫 조문을 근거로 채택하지 않는다.
- 체인 단위 deadline과 abort signal을 공유한다. 시간 안에 받은 결과를 유지하고 미수집 부분과 개별 조회 힌트를 반환한다.

채택: 체계도·조례·시점·인용 확인을 기존 체인으로 활용하고, 부분 결과와 누락을 구조화해서 플랫폼 작업으로 저장한다.

제한: applicable-law 코드도 경과조치의 발췌와 해석을 구분한다. 부칙 몇 줄을 추출한 것으로 적용 문제를 해소했다고 판단하지 않는다. 자유 텍스트의 자동 task/scenario 보정은 UX 참고로 두고, 플랫폼 계약에서는 명시된 필드를 엄격히 검증한다. 코드와 README의 버전 표현이 달라 실제 commit와 discovery 결과를 고정해야 한다.

## 3. ACCORD: 규칙 작성에서 실행까지

원본: [형식화 절차](https://docs.accordproject.eu/process/), [오케스트레이션](https://docs.accordproject.eu/orchestration/), [API 구분](https://docs.accordproject.eu/apis/), [AEC3PO RASE 모듈](https://github.com/Accord-Project/aec3po/blob/main/src/rase_statement.ttl).

처리 흐름: 문서 구조화→조항과 논리 식별→RASE 분해→조건 표현식→용어와 데이터 취득 방법 매핑→규칙 저장→필요 검사 선택→실행→상태/결과 조회.

실행 서비스는 기능 등록부를 조회하고, 규칙에 필요한 용어/데이터를 처리할 수 있는 서비스를 선택한다. API는 규칙·모델 데이터·결과의 책임을 구분하며 결과 처리를 비동기로 설계한다.

채택: 규칙 작성 양식, 적용/요구/선택/예외 구분, 실행 데이터 바인딩, 공급자 기능 등록부, 비동기 run/status/results 패턴.

제한: 문서는 전체 제품을 한국 법령 데이터와 함께 제공하지 않는다. RASE의 객체 검사 의미를 법령 간 예외·특례 전체에 기계적으로 확장하지 않는다. bSDD는 BIM 용어 정렬에 유용하지만 한국 법령의 정의와 관할 의미는 별도로 모델링한다. 현재 compiler가 지원하지 않는 식은 REVIEW로 남긴다. AEC3PO 모듈에서 CC BY 4.0을 확인했으며 외부 imports의 조건은 개별 확인한다.

## 4. KAG: 질문 분해와 검색 결과의 원문 연결

원본: [KAG 개요](https://github.com/OpenSPG/KAG), [hybrid executor](https://github.com/OpenSPG/KAG/blob/master/kag/solver/executor/retriever/local_knowledge_base/kag_retriever/kag_hybrid_executor.py).

개요는 스키마를 제약으로 사용해 지식을 만들고 계획·추론·검색 연산자를 조합하는 구조를 설명한다. 읽은 executor 구간은 chunk와 그래프 SPO 결과를 참조 목록으로 정리하고 sub-question 결과를 추적하는 데이터 모델을 포함한다.

채택: 질문을 필요한 사실·법령·계산·예외 확인으로 나누는 방식, 각 단계의 자료/참조를 보존하는 원칙.

보류: OpenSPG/KAG 전체 도입. 현재 ArchOntos/LightRAG와 중복되는 저장·검색·운영 체계가 추가된다. README의 일반 벤치마크 성능 주장만으로 한국 법규 정확성이 더 높다고 판단하지 않는다. 읽은 코드 구간만으로 전체 추론 절차를 검증했다고 주장하지 않는다.

## 5. LightRAG: 현재 엔진을 제한된 근거 검색에 활용

원본: [Core 문서](https://github.com/HKUDS/LightRAG/blob/main/docs/ProgramingWithCore.md). 로컬에는 `SionGraphRag`, `build_custom_kg`와 LightRAG 1.5.7 pin이 있다.

채택: existing custom KG에 공식 관계와 검토된 assertion을 넣고 그래프·텍스트 검색 문맥을 얻는다. source ID를 실제 원문·DB ID와 연결해 설명에 사용한다.

필수 수정 설계: 현재 projection은 모든 entity와 유효기간의 relation을 읽으며 review-state/권한/프로젝트별 분리는 명시되어 있지 않다. source evidence의 문구에 unverified가 적혔다는 이유만으로 생성 모델이 확정 근거로 사용하지 않을 것을 기대해서는 안 된다. 투영 이전에 범위를 제한하고 답변의 근거 사용도 검증한다. upstream 최신 저장소 클래스/옵션을 pinned 버전에 바로 사용하지 않는다.

## 6. 표준과 실행 지침

| 자료 | 설계에 가져올 것 | 구분해야 할 것 |
|---|---|---|
| [GeoSPARQL 1.1](https://docs.ogc.org/is/22-047r1/22-047r1.html) | feature/geometry와 교차·포함 관계 용어 | 공간 교차와 법적 지정의 적용은 별도 근거 |
| [SHACL Recommendation](https://www.w3.org/TR/shacl/) | RDF 투영의 필수 구조·관계 제약 검증 | 구조 검증은 법적 진실 판정이 아님. 이번 검색의 1.2 문서 대신 채택안은 확인된 Recommendation 기준 |
| [LegalRuleML](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/os/legalruleml-core-spec-v1.0-os.pdf) | 예외·충돌·시간·관할·원문과 규칙의 연결 | 표준은 한국 규칙 집합이나 완성 추론 엔진이 아님 |
| [Temporal 오류 처리](https://docs.temporal.io/develop/python/best-practices/error-handling) | idempotency, 일시/영구 오류 분류, checkpoint/복구 요구 | 지침 참고와 서버/SDK 도입은 별도 결정 |

## 7. 설계 결정 기록

| 결정 | 선택 | 대안/보류 이유 | 변경 조건 |
|---|---|---|---|
| 법령 후보 기반 | 공식 지역지구·관할·행위 연결 | 키워드 카탈로그만으로 커버리지 확보 어려움 | 공식 연결 범위 밖은 보조 검색과 검토 카탈로그 추가 |
| canonical 평가 | ArchOntos | Gateway·Sion 양쪽에 평가 중복 저장/편집하지 않음 | 서비스 분리가 필요해도 소유권 유지 |
| 법령/토지 수집 | 기존 MCP와 공식 API 어댑터 | 전면 재작성은 비용과 실패 지점 증가 | 동등성 시험에서 기존 공급자가 필수 데이터 미지원 |
| 규칙 작성 | ACCORD/RASE 지침 + 현행 DSL | 새 언어/BCRL 전체 구현은 초기 부담 | 검토된 규칙이 현행 DSL에서 표현 불가하고 필요성 확인 |
| 검색 | 현행 LightRAG | KAG/GraphRAG 전면 교체는 격리/운영 부담 | 동일 golden set 비교에서 명확한 이익과 호환성 확보 |
| 공간 처리 | 현행 계산 + GeoSPARQL 용어 정렬 | 새 RDF 공간 엔진/DB 추가 보류 | 규모/질의 요구로 현행 방식 한계가 측정됨 |
| 실행 | DB 상태·outbox·작업자 | Temporal 전체 도입 보류 | 재개/예약/운영 시험에서 기존 구조가 요구 미달 |
| 사용자 화면 | 프로젝트 검토/작업/브리핑 | 상태 숫자 중심 별도 대시보드 확장 보류 | 실제 사용자 작업에서 추가 화면 필요 확인 |

## 8. GitHub 읽기 증거

아래 SHA는 GitHub fetch_file이 반환한 **파일 blob SHA**다. repository commit pin과는 다르며, 향후 도입 시 전체 commit을 별도로 고정해야 한다. 표의 파일은 모두 일부 구간을 읽었다.

| 저장소/파일 | blob SHA |
|---|---|
| UrbanWatcherKr/korean-land-mcp · src/tools/analyze_parcel.ts | 14db8bdcd29c000c09fc1da02a786c221d58c156 |
| UrbanWatcherKr/korean-land-mcp · src/lib/overlays.ts | 6da867cc5c462dcd0eea3e0335efdba350063759 |
| chrisryugj/korean-law-mcp · src/tools/legal-research.ts | 30f15c1f24781aeabc1fad2e5286cbfe5e3edebb |
| chrisryugj/korean-law-mcp · src/tools/applicable-law.ts | 1c5cddc535dab772534bbb5932d6ac2521a47bd7 |
| chrisryugj/korean-law-mcp · src/tools/chain-deadline.ts | 429571d4e6af399caf16b200617d470e6f119e21 |
| Accord-Project/aec3po · src/rase_statement.ttl | a6493b00b88046d4591cea832770726fb8f5afc3 |
| OpenSPG/KAG · README.md | 189179325180dcc7de0341ae6b8c64a6a97b2daa |
| OpenSPG/KAG · kag/solver/executor/retriever/local_knowledge_base/kag_retriever/kag_hybrid_executor.py | 48628716624a626b5904c1bf6a7bb1fb52b9b2d4 |
| HKUDS/LightRAG · docs/ProgramingWithCore.md | 1bc57e8037c3ab477dddcf67db751c7a440a53c4 |
| khs0927/Ontology-platform · packages/regulation/src/archontos/rules/compiler.py | e0b32bbe3482646df307eb3fa5e300e1557f9b03 |

로컬 확인 기준 HEAD: Ontology-platform `4cbf015a2d9baff5744356f16862c3f9e57a109a`, Gateway `3b73927a7d1837d0e1b55d9b82d4dbdb7db3390a`. 미커밋 변경은 이전 작업에서 존재하며 이번 조사에서는 변경하지 않았다.
