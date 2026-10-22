# SketchUp 에이전트 GraphRAG 플레이북

이 문서는 SketchUp MCP 에이전트가 모델을 변경하기 전에 Ontology-platform의 GraphRAG 지식을 조회하고, 근거를 확인한 뒤 작업으로 옮기는 절차를 정리한다. 대상 지식은 `0914_담당미팅.skp`의 읽기 전용 덤프와 한국어 모델링 지침이며, 분류와 지침 연결은 `/review` 전까지 `unverified` 후보라는 점을 전제로 한다.

## 0. 공통 원칙

1. 먼저 읽는다. `get_model_info`, 단위·범위·수량, 대상의 bbox와 현재 태그/재질을 확인한다.
2. GraphRAG의 분류 엣지는 추론 후보다. 치수·레벨·재질·인스턴스 수는 `def:`, `obj:`, `occ:` 사실 노드에서만 가져온다.
3. 요청된 변경만 수행한다. 저장, purge, delete는 사용자 요청 없이는 하지 않는다.
4. 작업 하나를 한 operation으로 묶고, 변경 후 bbox·태그·재질·단위를 다시 읽는다. `regroup_0914.rb`는 기본 `DRY_RUN = true` 계획 확인용이며 에이전트가 false로 실행하지 않는다.
5. 근거가 충돌하거나 후보가 승인되지 않았으면 실행하지 말고 `/review` 또는 사용자 판단으로 넘긴다.

GraphRAG 쿼리 API는 `read:knowledge` 권한이 필요하다.

- 엔드포인트: `POST /api/v1/graphrag/query`
- 요청 필드: `question`(1–2000자), `mode`(`local|global|hybrid|naive|mix`), `top_k`(1–200)
- 기본 모드와 `top_k`는 각각 `mix`, 20이다.

요청 예:

```http
POST /api/v1/graphrag/query
Content-Type: application/json

{"question":"SketchUp 옹벽을 그리는 순서와 이 모델의 옹벽 근거를 알려줘","mode":"mix","top_k":12}
```

LLM이 설정되지 않은 서버는 검색 문맥만 반환한다.

```json
{"canonical":false,"mode":"mix","context":"<LightRAG가 반환한 검색 문맥>"}
```

`SION_GRAPHRAG_LLM_MODEL`이 설정된 서버는 답변을 반환한다.

```json
{"canonical":false,"mode":"mix","answer":"<LightRAG가 생성한 답변>"}
```

위 두 응답 예에서 꺾쇠 괄호 부분은 실제 서버가 반환하는 값이며, `context`와 `answer`를 동시에 있다고 가정하지 않는다.

## 1. 지식 그래프를 읽는 법

주요 노드:

- `sketchup:class:<id>`: 30개 객체 클래스. 예: `retaining-wall`, `parking-deck`, `building`, `curtain-wall`.
- `sketchup:guide:<id>`: `MODELING-GUIDELINES.ko.md`의 31개 지침 절.
- `sketchup:0914-meeting:def:<slug>`: 정의별 크기·면·재질·태그·프로브 사실.
- `sketchup:0914-meeting:obj:<persistent_id>`: 상위/2단계 배치의 월드 bbox와 변환.
- `sketchup:0914-meeting:occ:<pid.pid...>`: 더 깊은 배치. 반복 복사 때문에 persistent-id 경로 전체를 사용한다.
- `sketchup:workflow:grouping`, `sketchup:grouping:step:<id>`, `sketchup:grouping:pattern:<id>`: 그룹화 워크플로와 관측 규칙.
- `sketchup:0914-meeting:model`, `sketchup:0914-meeting:dump`: 모델 메타데이터와 원본 덤프.

주요 관계:

- `PART_OF`: 정의/배치/지침이 모델·상위 배치·워크플로에 속함.
- `USES`: 모델·배치·지침이 태그, 재질, MCP 도구를 사용함.
- `REFERENCES`: 배치가 정의를 가리키거나 지침이 객체 클래스를 참고함.
- `DERIVED_FROM`, `EXTRACTED_FROM`: 덤프·프로브·지침이 모델 근거에서 유도됨.
- `IMPLEMENTS`, `SUPPORTS`: 분류 후보와 그룹화 규칙/워크플로 연결.
- `DEPENDS_ON`, `RELATED_TO`: 순서가 있는 지침·그룹화 단계 연결.

분류·지침 연결 후보는 `properties.candidate = true`와 `verification_state = "unverified"`를 확인한다. 승인 작업은 명시적인 후보 id 목록에 대해 `POST /api/v1/relations/candidates/bulk`와 `{"ids":[...],"decision":"approve"|"reject","note":"...","reviewer":"..." }`를 사용하며, 승인 여부를 에이전트가 추측하지 않는다.

## 2. 새 객체 그리기

### 조회

먼저 질문을 객체 클래스와 지침에 매핑한다.

```json
{"question":"SketchUp 외부 계단을 새로 만들 때 필요한 단계·치수 확인·이 모델의 예시는?","mode":"mix","top_k":12}
```

기대할 근거:

- `sketchup:class:exterior-stair`
- `sketchup:guide:exterior-stair`
- 필요하면 `sketchup:guide:levels`, `sketchup:guide:agent-judgement`
- 모델 사실은 `sketchup:0914-meeting:def:그룹-19`, `그룹-23`, `그룹-31` 같은 정의 노드와 배치 노드

옹벽이면 질문을 다음처럼 좁힌다.

```json
{"question":"옹벽을 만들 때 근거 재질, 레벨, MCP 작업 순서와 이 모델의 사례를 알려줘","mode":"mix","top_k":12}
```

이때 `sketchup:guide:retaining-wall`, `sketchup:guide:materials`, `sketchup:class:retaining-wall`와 `그룹-16`, `그룹-29`, `그룹-35` 정의의 사실을 확인한다.

### 작업으로 옮기기

1. `get_model_info`로 단위가 mm인지 확인한다.
2. `find_components` 또는 `list_components(recursive=true)`로 대상 위치와 bbox를 확인한다.
3. 단일 박스/원기둥이면 `sketchup-mcp2.create_component(type, position=bbox 최소점, dimensions mm, name)`처럼 mm를 명시한다.
4. 면/경사면이면 `hueflow.create_face`, `hueflow.push_pull` 또는 읽기·계산용 `hueflow.execute_ruby`를 사용한다.
5. 응답의 `bbox_mm`와 새 객체의 태그·재질·레벨을 다시 조회한다.
6. 지침이 요구하는 순서·단위·근거를 충족하지 못하면 변경을 확정하지 않고 사용자에게 되돌린다.

## 3. 그룹화·컴포넌트화

### 조회

```json
{"question":"반복되는 기둥과 가구를 컴포넌트로 묶고 건물 조립체를 중첩할 때 어떤 규칙과 순서를 따르는가?","mode":"mix","top_k":16}
```

확인할 노드:

- `sketchup:guide:group-component`
- `sketchup:guide:grouping-overview`
- `sketchup:grouping:pattern:component-for-repeats`
- `sketchup:grouping:pattern:nest-by-assembly`
- `sketchup:grouping:pattern:default-naming`
- 해당 단계인 `sketchup:grouping:step:step-repeats`, `step-building-container`, `step-verify-cleanup`

`GROUPING-WORKFLOW.ko.md`에는 11개 관측 규칙과 12개 순서 단계가 있다. 단계는 `DEPENDS_ON`/ `RELATED_TO`로 이어지므로 중간 단계를 건너뛰지 않는다.

### 작업 순서

1. `step-inspect`에 해당하는 모델·레이어·최상위 구조를 읽는다.
2. 반복 여부와 정의 원점을 `component-for-repeats`, `definition-origin` 근거로 확인한다.
3. 반복 요소는 `sketchup-mcp2.create_component`/정보 조회 또는 `hueflow.place_component` 흐름으로 옮긴다.
4. 조립체는 `hueflow.create_group` 또는 기존 컴포넌트 구조를 유지하며 `nest-by-assembly` 기준으로 묶는다.
5. 이름·태그·레벨을 검증하고, `step-verify-cleanup`에 해당하는 정리/QA를 수행한다.
6. `regroup_0914.rb`는 계획 출력만 읽는다. 모델 저장·purge·삭제·실제 적용은 별도의 사용자 승인이 필요하다.

## 4. 레이어·태그 정리

### 조회

```json
{"question":"SketchUp의 도로계획, @wall, Trees 3D 태그를 어떻게 점검하고 원시 형상에 적용하는가?","mode":"mix","top_k":14}
```

기대할 근거:

- `sketchup:guide:tags`
- `sketchup:grouping:pattern:tags-on-raw-geometry`
- `sketchup:guide:cad-import` 및 `sketchup:guide:cleanup`
- `sketchup:0914-meeting:tag:도로계획`, `tag:at-wall`, `tag:trees-3d`, 관련 `def:`·`obj:` 노드

### 작업 순서

1. `hueflow.list_layers`와 `sketchup-mcp2.list_layers`로 실제 레이어/태그 이름을 읽는다.
2. CAD 참조, 주석, 나무, 난간처럼 원시 형상에 직접 붙은 태그인지 확인한다.
3. 이름이 비슷한 태그를 합치지 말고 GraphRAG의 실제 tag 노드와 대조한다. `@wall`과 `WALL`처럼 구별되는 이름이 있을 수 있다.
4. 사용자가 명시한 경우에만 `sketchup-mcp2.create_layer`나 태그 변경을 수행한다.
5. 변경 후 레이어 가시성, 대상 수, bbox를 다시 읽는다. 임시 `LIBFREDO6_TEMP_LAYER`·작업 표시는 `cleanup` 근거와 사용자 결정 없이 삭제하지 않는다.

## 5. 도면화·장면 확인

### 조회

```json
{"question":"현재 SketchUp 모델을 도면화하기 전에 장면·단면·품질검사를 어떻게 확인하는가?","mode":"mix","top_k":14}
```

기대할 근거:

- `sketchup:guide:scenes`
- `sketchup:guide:qa`
- `sketchup:guide:mcp-execution`
- `sketchup:0914-meeting:model`, `scene:1`, `scene:2`, `scene:3`, `section:1`

### 작업 순서

1. 모델 단위·범위·층 레벨과 장면/단면 존재를 읽는다.
2. `sketchup-mcp2.list_components`, `get_component_info`, `hueflow.execute_ruby`로 대상과 품질검사 항목을 점검한다.
3. 장면을 외부로 내보내는 요청이면 `sketchup-mcp2.export_scene`을 사용한다.
4. 장면·카메라·단면 결과가 요청과 맞는지 확인한다. `render_views.rb`는 카메라를 바꾸고 복원하는 읽기용 렌더 절차지만 PNG는 커밋하지 않는다.
5. 실제 모델 변경이 필요한 도면화와 단순 장면 export를 구분하고, 전자는 사용자 요청 범위를 넘지 않게 한다.

## 6. 불확실성·/review 넘김 기준

다음 중 하나면 작업을 확정하지 않는다.

- GraphRAG가 반환한 class/guide 연결이 `unverified` candidate이고, 질문이 그 연결의 승인 여부에 의존한다.
- 같은 객체에 서로 다른 클래스·태그·레벨 근거가 충돌한다.
- 치수·재질·bbox가 class 설명과 다르고 사실 노드로 확인할 수 없다.
- 변경이 저장, purge, delete, 태그 삭제, 원본 덮어쓰기를 포함한다.
- MCP 응답에 `bbox_mm` 또는 작업 후 읽기 검증이 없고 결과를 확인할 수 없다.
- 데이터에 없는 API 필드·노드·관계를 추정해야 한다.

이 경우:

1. 사용한 질문과 `mode`, `top_k`를 기록한다.
2. 어떤 node/edge와 source locator가 충돌했는지 적는다.
3. 후보 id를 확인할 수 있으면 `/review`에서 사람이 approve/reject하도록 넘긴다.
4. 사용자가 실제 모델 변경을 원하면 변경 범위와 되돌리기 방법을 확인받는다.

## 근거 파일

- [SketchUp knowledge](../SKETCHUP_KNOWLEDGE.md)
- [모델링 지침](MODELING-GUIDELINES.ko.md)
- [그룹화 워크플로](GROUPING-WORKFLOW.ko.md)
- [GraphRAG API/레이어](../GRAPHRAG.md)
- [추출 스크립트 README](../../scripts/sketchup/README.md)
- [생성기](../../packages/ingestion/sion_ingestion/sketchup_assets.py)
