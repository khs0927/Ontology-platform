# 온톨로지 적용 범위

`cad-core.ttl`은 GOD-CAD가 작성한 작은 실험용 어휘다. 전체 건축 온톨로지가 아니며 JSON 모델을 자동으로 OWL 추론한 결과도 아니다. 저장소 소유 경로를 namespace로 사용한다. 별도 vocabulary hosting은 아직 없다.

`example-candidate.ttl`은 WAL1 레이어에서 얻은 **벽 후보**를 보여준다. 후보에 `rdf:type beo:Wall`을 단정하지 않고 `cad:proposedClass`와 근거를 기록한다. 실제 분석 결과의 RDF 내보내기는 후속 작업이다.

| 외부 자산 | 결정 |
| --- | --- |
| BEO | v0.1 후보 분류에서 Wall/Door/Window/Column URI 참조 |
| BOT | 후속 공간 모델의 Building/Storey/Space 정렬 대상 |
| OMG/FOG | 후속 geometry 표현 연결 설계에 사용; 정확한 property/version 검증 후 채택 |
| PROV-O | 자체 DrawingRevision/SourceEntity/활동의 의미 정렬 참고 |
| IFC/bSDD | 후속 교환·개념 사전 매핑; 초기 실행 의존성 없음 |
| SHACL | 후속 의미 그래프 검증; 현재는 JSON/Pydantic 검증만 실행 |

외부 온톨로지 전체를 복사하거나 네트워크에서 자동 import하지 않는다. 실제 통합 시 namespace, 정확한 버전/commit, 다운로드 checksum, 이용 조건, mapping 근거를 manifest로 고정한다. `owl:sameAs`는 개념이 비슷하다는 이유만으로 사용하지 않는다.
