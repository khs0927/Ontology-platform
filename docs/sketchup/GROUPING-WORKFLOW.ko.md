# SketchUp 그룹화·정리 워크플로 (근거 모델: 0914_담당미팅.skp)

이 문서는 `0914_담당미팅.skp`의 **그룹·컴포넌트·태그를 어떻게 묶었는지**를 읽기 전용 그룹화 프로브
(`data/sources/sketchup/0914-meeting/grouping_probe.json`, `scripts/sketchup/grouping_probe.rb`)와 모델 덤프
(`model_dump.json`)로 분석하고, 그 결과를 **순서가 있는 작업 단계(워크플로)**로 다시 정리한 것입니다.
`MODELING-GUIDELINES.ko.md`의 `group-component` 절을 자세히 풀어 쓴 문서입니다.

GraphRAG 청크 규칙: `##` 절 하나가 노드 하나가 됩니다. `kind="pattern"` 절은 관측 규칙(Decision,
`sketchup:grouping:pattern:<id>`), `kind="step"` 절은 워크플로 단계(Workflow, `sketchup:grouping:step:<id>`),
`kind="index"` 절은 문서(Document)입니다. 단계 노드는 `sketchup:workflow:grouping`에 `PART_OF`로 붙습니다.
앞 단계에는 `DEPENDS_ON`(follows_step)로, 다음 단계에는 `RELATED_TO`(precedes)로 이어지고, 적용하는 규칙에는
`IMPLEMENTS`(applies_rule)로 연결됩니다. 근거 표기 `occ:<pid.pid…>`는 루트에서 그 인스턴스까지의
persistent id 경로(3단계 이상 깊이), `obj:<pid>`는 최상위·2단계 인스턴스입니다.

표기: **[관측]** 프로브·덤프에서 바로 읽은 사실(mm, 월드 좌표). **[추론]** 사실을 해석한 내용(검토 전).
**[권장]** 새 모델에 적용할 규칙. 작업 순서 자체는 모델에 기록이 없어서 결과물로부터 재구성한 **[추론]**입니다.
최상위 persistent id 크기 순서(작을수록 먼저 만들어졌을 가능성)를 보조 근거로 썼습니다.

## 그룹화 분석 개요와 계층 통계
<!-- sion-guide id="grouping-overview" order="1" kind="index" applies_to="site-container,building,terrain,furniture,tree" tools="hueflow.list_entities,hueflow.execute_ruby,sketchup-mcp2.list_components" evidence="model:0914,grouping-probe:nodes,obj:30598,obj:511546,obj:1458557" -->

**[관측] 계층 통계** (그룹화 프로브, 2026-10-08 11:06:29 +0900, 모델 저장 안 된 상태 `model_modified=true`, 편집 경로 없음)
- 그룹/컴포넌트 인스턴스는 모두 619개이고, 가장 깊은 중첩은 7단계(depth 0–6)입니다.
- 깊이별 개수: 0:18 · 1:58 · 2:130 · 3:68 · 4:168 · 5:95 · 6:82.
- 정의는 그룹 229개와 컴포넌트 68개입니다. 그룹 정의 228개는 기본 이름(`그룹#N`, `그룹N#1`)을 그대로 씁니다.
- 잠긴 인스턴스(`locked`)와 숨긴 인스턴스(`hidden`)는 0개입니다. 면에 붙은(glued) 인스턴스는 `그룹#133` 1개뿐입니다.
- 반전(mirror) 배치는 18개, 부모 좌표계와 변환이 같은(identity) 그룹 인스턴스는 54개입니다.
- 가장 깊은 사슬 예시:
  - 별동 루버: `그룹#201 > 그룹#161 > 그룹#101 > 그룹#76 > 그룹#79 > 그룹167#1 > 그룹169#1`
  - 미닫이문: `그룹#201 > 그룹#129 > 그룹#159 > 그룹#122 > 그룹#250 > 그룹#249 > 그룹#257`
  - 2층 의자 부품: `그룹#201 > 그룹#202 > 그룹#205 > 그룹#232 > ch5 > 그룹#98`

**[관측] 최상위 18개 인스턴스** (모두 태그 `Layer0`). 표기는 정의(분류), Z 회전입니다.
- `학장동 skp.dwg`(site-container, 4.09°)
- `그룹#18`(exterior-stair, 4.09°)
- `그룹#34`(retaining-wall, 4.09°)
- `그룹#38`(terrain, 4.09°)
- `그룹#40`(paving, 0°)
- `그룹#201`(building, 0°)
- `그룹#65`(tree, 0°)
- `그룹#89`(beam, 0°)
- `새 블럭.dwg`(curtain-wall, −90°)
- `그룹#39`·`그룹#102`(terrain, 0°)
- `그룹#12` ×2(marker)
- `그룹#105`(building = 1층 실내, −90°)
- `col` ×4(column)

**이 문서의 구성**
- 규칙(pattern) 11개: 작성자가 실제로 쓴 묶는 방식입니다.
- 단계(step) 12개: 그 방식을 새 모델에 그대로 재현하는 순서입니다.
- 각 단계에는 입력, 판단 규칙, 그룹·이름·태그 작업, MCP 호출(Ruby는 mm 단위), 검증, 근거가 들어 있습니다.

## 규칙 1 — 최상위는 건물 부위·구역별 그룹 (태그·층별이 아님)
<!-- sion-guide id="top-split-by-part" order="2" kind="pattern" applies_to="site-container,building,exterior-stair,retaining-wall,terrain,paving,tree,beam,column,marker" tools="hueflow.list_entities,sketchup-mcp2.list_components" evidence="obj:30598,obj:47944,obj:90359,obj:125087,obj:125433,obj:511546,obj:800070,obj:1171922,obj:1181414,obj:1458557,tag:Layer0" -->

**[관측]**
- 최상위 18개는 모두 `Layer0`에 있습니다. 태그나 층이 아니라 **대지 CAD / 외부계단 / 옹벽 / 동측 조경 / 포장 슬래브 / 본동 / 수목 / 보 / 2층 핀 / 지형 / 표식 / 1층 실내 / 기둥**처럼 부위와 구역으로 나뉘어 있습니다.
- 본동 `그룹#201`에는 직접 하위 23개(그룹 22, 컴포넌트 1)가 들어 있고, 하위 전체는 422개입니다. 내용은 다음과 같습니다.
  - 사람 5개
  - 보 `그룹#225`, 벽 `그룹#109`
  - 난간 `그룹#258`·`그룹#67`, 유리난간 `그룹#115`·`그룹#124`
  - 커튼월 `그룹#85`·`그룹#129`
  - 별동 `그룹#161`·`그룹#217`
  - 슬래브 `그룹#103`, 슬래브·천장·지붕 묶음 `그룹#202`
  - 화분 `그룹#62`·`그룹#72`·`그룹#73`
- 1층 실내는 본동과 따로 최상위 `그룹#105`(−90°) → `그룹#160`으로 묶였습니다. `그룹#160` 안에는 의자 `C1` 47, 테이블 `T` 8·`T2` 5, 소파 `SO` 8, 카운터 4개, 실내계단 `그룹#111`, 커튼월 프레임 `그룹#46`이 있습니다.

**[추론]** 작업 단위(“이번에 고칠 덩어리”)로 최상위를 나눴습니다. 태그는 쓰지 않고 그룹을 열고 닫는 방식으로 편집 범위를 관리한 것으로 보입니다.

**[권장]** 이 원칙은 유지합니다. 다만 최상위 그룹에 `SITE-`, `BLDG-`, `INT-1F-`처럼 부위가 보이는 이름을 붙이고, 부위별 태그(예: `A-대지`, `A-본동`, `A-실내`)를 **최상위 그룹에만** 지정해 가시성을 제어합니다.

## 규칙 2 — 조립체 → 하위 조립체 → 부재 순의 깊은 중첩
<!-- sion-guide id="nest-by-assembly" order="3" kind="pattern" applies_to="building,floor-slab,roof,curtain-wall,door,window-louver,furniture" tools="hueflow.list_entities,hueflow.execute_ruby" evidence="obj:4577802,def:그룹#202,def:그룹#203,def:그룹#205,def:그룹#207,occ:511546.4577805.4164146.4164144.4163927.4163488.4163456,occ:511546.4577801.4204624.4204575.4204512.4204509.4204480,def:그룹167#1" -->

**[관측]**
- 본동 하위 `그룹#202`(본동 안 로컬 Z +5300)는 형상 없이 하위 그룹 4개만 가진 컨테이너입니다. 하위는 층별로 나뉩니다.
  - `그룹#203`: 1층 천장. 접힌 천장 `그룹#133`을 품고 있습니다.
  - `그룹#205`: 2층 바닥과 가구(`c3` 6, `ch5` 3, `ch6` 5, `그룹#226`, `그룹#232`).
  - `그룹#207`: 지붕(`그룹#214`·`그룹#211`·`그룹#223`).
  - `그룹#222`.
- 정의 역할(사용 중인 정의)
  - 그룹: 말단(형상만) 144, 혼합(형상+하위) 42, 컨테이너(하위만) 32.
  - 컴포넌트: 말단 13, 컨테이너 4, 혼합 3.
- 하위 인스턴스가 가장 많은 정의: `그룹#68` 30, `그룹167#1` 24(루버 살 `그룹169#1`…`그룹192#1`), `그룹#65` 13, `그룹#232` 8, `그룹#258` 7.

**[추론]**
- 깊이가 6까지 내려가는 것은 “부재를 만든 뒤 묶고, 묶음을 다시 위 묶음에 넣는” 상향식 작업 때문입니다. 예: 루버 살 → 루버 세트 → 창 → 별동 외피 → 별동 → 본동.
- 같은 정의 안에 형상과 하위 그룹이 섞인 혼합 정의가 55개입니다(사용·미사용 합계). 예: `그룹#160` 직접 형상 83 / 하위 74, `그룹#201` 모서리 9. 묶은 뒤에 그 안에서 직접 형상을 더 그린 흔적으로 보입니다.

**[권장]**
- 깊이는 4–5단계 이내로 둡니다.
- 컨테이너 그룹은 형상을 갖지 않게 합니다. 기준선이 필요하면 별도의 `REF-` 그룹으로 분리합니다.

## 규칙 3 — 반복 부재는 컴포넌트, 복사 부재는 같은 정의의 그룹 복제
<!-- sion-guide id="component-for-repeats" order="4" kind="pattern" applies_to="furniture,column,tree,handrail,window-louver,person" tools="sketchup-mcp2.find_components,sketchup-mcp2.get_component_info,sketchup-mcp2.create_component,hueflow.place_component" evidence="def:C1,def:ch5,def:T,def:SO,def:col,def:그룹#57,def:그룹#74,def:그룹#98,def:Component#28,occ:511546.4577802.4361373.4360622.4360577" -->

**[관측]**
- 컴포넌트로 만든 반복 부재(배치 수): `C1` 47, `ch5` 11, `c3#2` 8, `T` 8, `SO` 8, `c3` 6, `ch6` 5, `T2` 5, `col` 4, 나무 `Component#28` 16(`그룹#74` 안 14, `그룹#53`·`그룹#56` 안 각 1).
- 그룹이지만 같은 정의를 복사해 쓴 반복 부재: `그룹#57`(이름 `D=15 mm`, `그룹#68` 안 29 × 2 = 58), `그룹#74` 14(`그룹#65` 안 11, 화분 `그룹#62`/`#72`/`#73` 안 각 1), `그룹#98` 11(의자 `ch5` 안), `그룹#175` 11 등.
- 나무 그룹 `그룹#74`는 비균일 축척으로 배치됐습니다: (0.4271, 0.4271, 0.457) 11개, 0.3203 3개.
- `그룹#53`·`그룹#56`은 `그룹#74`와 내용이 같은 별도 정의입니다(복제된 정의).
- 반전 배치 18개: `그룹#98` ×11, `그룹#119`, `그룹#110`, `그룹#139`, `그룹#253`, `그룹#122`, `그룹#254`, `그룹#184`.

**[추론]**
- 가구·기둥처럼 **이름 붙여 관리할 부재는 컴포넌트**로 만들었습니다.
- 난간 파이프·루버 살·나무처럼 **현장에서 바로 복사한 부재는 그룹 복사**로 처리했습니다. 그룹을 복사해도 정의를 공유하므로 사실상 컴포넌트처럼 동작합니다.
- 좌우 대칭 부재는 축척 −1(반전)로 복사했습니다.

**[권장]**
- 2개 이상 반복되는 부재는 처음부터 **이름 있는 컴포넌트**로 만듭니다.
- 비균일 축척이나 반전 복사가 필요하면 별도 정의(`Make Unique`)로 만들지, 축척만 다른 같은 정의로 둘지를 기록해 둡니다.

## 규칙 4 — 이름은 기본값, 컴포넌트만 짧은 코드
<!-- sion-guide id="default-naming" order="5" kind="pattern" applies_to="furniture,column,handrail,person,unused-definition" tools="sketchup-mcp2.list_components,hueflow.list_components,hueflow.execute_ruby" evidence="def:그룹#57,def:그룹#83,def:그룹#19,def:그룹36#1,def:C1,def:T2,def:Component18,def:Humano4_262" -->

**[관측]**
- 그룹 정의 229개 중 228개가 자동 이름(`그룹#N`, 복제 시 `그룹N#1`)입니다.
- 컴포넌트는 짧은 코드(`C1`, `T`, `T2`, `SO`, `ch5`, `ch6`, `c3`, `c3#2`, `col`)를 씁니다.
- 인스턴스 이름은 플러그인·가져오기에서 온 것만 있습니다.
  - `D=15 mm` ×58(`그룹#57`), `D=30 mm` ×7(`그룹#83` ×2, `그룹#25`–`#28`, `그룹#259`)
  - `Raise`(`그룹#19`·`그룹#23`), `Handrail`(`그룹36#1`·`그룹53#1`)
  - `Humano4_*` 사람, `CWom0105-…`(`Component18`)

**[추론]**
- `D=… mm`, `Raise`, `Handrail`은 계단·난간 생성 플러그인이 자동으로 붙인 이름입니다.
- 작성자는 이름이 아니라 **위치와 열기(편집)**로 객체를 찾았습니다.

**[권장]** 최상위와 2단계 그룹은 `부위-층-요소`로 이름 짓습니다. 예: `BLDG-2F-SLAB`, `SITE-RW-01`.

## 규칙 5 — 태그는 인스턴스가 아니라 CAD 잔여 형상에만 남아 있음
<!-- sion-guide id="tags-on-raw-geometry" order="6" kind="pattern" applies_to="cad-reference,road-plan-surface,handrail,tree,annotation" tools="hueflow.list_layers,sketchup-mcp2.list_layers,hueflow.execute_ruby" evidence="tag:Layer0,tag:도로계획,tag:XCLINE,tag:Trees 3D,tag:@win,tag:@0818변경,def:그룹#6,def:그룹#45,def:그룹#83,def:그룹#74" -->

**[관측]**
- 인스턴스 619개 중 `Layer0`이 아닌 것은 나무 컴포넌트 `Component#28`(`Trees 3D`, 깊이 2에 13개, 깊이 3에 3개)뿐입니다.
- 사용 중인 정의에서 `Layer0`이 아닌 **직접 형상**은 다음과 같습니다(21개 정의).
  - `도로계획` 모서리: 대지 그룹 안. `학장동 skp.dwg` 88, `그룹#6` 68, `그룹#45` 56, `그룹#1` 36, `그룹#14` 32, `그룹#7` 21, `그룹#8` 12, `그룹#5` 4, `그룹#30` 4.
  - `XCLINE` 모서리: 난간 파이프 안. `그룹#83` 27, `그룹#259` 6, `그룹#25`–`#28` 각 3, `그룹#57` 1.
  - `@win` 1개(`그룹#63`), `@0818변경` 4개(`그룹#42`).
  - `Trees 3D`: 나무 그룹 `그룹#74`·`#53`·`#56`의 전체 형상.

**[추론]**
- 면을 CAD 선 위에 그려서 모서리가 CAD 태그를 그대로 물려받았습니다.
- 난간 파이프는 CAD `XCLINE` 선을 Follow Me 경로로 썼습니다.
- 태그를 의도적으로 지정한 것은 나무(가져온 3D 모델)뿐입니다.

**[권장]**
- 태그는 **최상위·2단계 그룹 인스턴스에만** 지정합니다.
- 내부 형상은 `Layer0`(SketchUp 2025 `Untagged`)로 정리합니다. 검증 단계 12의 Ruby로 확인합니다.

## 규칙 6 — 대지 3D 그룹은 CAD 컴포넌트 안에서 CAD 선 위에 작성
<!-- sion-guide id="cad-host-nesting" order="7" kind="pattern" applies_to="site-container,cad-reference,retaining-wall,paving,road-plan-surface" tools="hueflow.execute_ruby,hueflow.create_face,hueflow.push_pull,sketchup-mcp2.get_component_info" evidence="obj:30598,def:학장동 skp.dwg,def:그룹#1,def:그룹#5,def:그룹#6,def:그룹#7,def:그룹#14,def:그룹#30,def:그룹#35,tag:도로계획" -->

**[관측]**
- `학장동 skp.dwg`는 가져온 CAD 컴포넌트입니다. 4.09° 회전, 원점 (3792.6, −6896.1, 0), 정의 최소점 (1116, −969, −9500).
- 그 안에 원본 CAD 모서리 94개(`도로계획` 88)와 면 7개가 있고, 3D 그룹 8개가 함께 들어 있습니다.
  - 그룹: `그룹#1`, `그룹#5`(paving), `그룹#6`(retaining-wall), `그룹#7`(road-plan-surface), `그룹#2`, `그룹#14`(retaining-wall), `그룹#30`(paving), `그룹#35`(retaining-wall).
- 같은 4.09° 회전을 쓰는 최상위 그룹은 `그룹#18`, `그룹#34`, `그룹#38`입니다. CAD 프레임에 맞춰 배치된 것입니다.

**[추론]**
- 작성자는 CAD 컴포넌트를 열고(편집 컨텍스트) 그 안에서 선을 따라 면을 만들고 그룹으로 묶었습니다.
- 그래서 대지 그룹이 CAD 정의의 하위가 되었습니다.
- 나중에 만든 계단·옹벽·조경은 CAD 밖에서 같은 회전으로 맞췄습니다.

**[권장]**
- 새 모델에서는 CAD를 참조용으로 잠그고, 3D 그룹은 **CAD 밖** 형제 그룹으로 둡니다.
- 회전은 CAD 쪽에 한 번만 두거나, 처음부터 대지 축에 맞춘 축(Axes)을 씁니다.

## 규칙 7 — 회전된 작업 프레임(4.09°, −90°)과 identity 복사
<!-- sion-guide id="rotated-frames" order="8" kind="pattern" applies_to="building,curtain-wall,site-container,window-louver,furniture" tools="hueflow.rotate_entity,sketchup-mcp2.transform_component,hueflow.execute_ruby" evidence="obj:1458557,obj:1181414,obj:4915226,obj:30598,def:그룹#105,def:새 블럭.dwg,def:그룹#54,def:그룹#175,def:그룹169#1" -->

**[관측]**
- 1층 실내 `그룹#105`: −90°, 원점 (808.7, 54872.7, 5000).
- 2층 핀 `새 블럭.dwg`: −90°, 원점 (60713.7, 44600, 5000). 하위에는 `그룹#54` 하나뿐이고, 원점 (200, 2350, 5200)에 놓여 있습니다.
- 대지 계열(`학장동 skp.dwg`, `그룹#18`, `#34`, `#38`)은 4.09°입니다. 본동 `그룹#201`은 0°입니다.
- 부모와 변환이 같은(identity) 그룹 54개가 있습니다. 예: `그룹#175` ×11, `그룹#150` ×8, `그룹#174` ×5, 루버 살 24개 `그룹169#1`–`그룹192#1`, `그룹#63`, `그룹#113`, `그룹#154`, `그룹#156`, `그룹#246`, `그룹#259`.
- 나머지 그룹 437개와 컴포넌트 128개는 이동·회전 변환을 가집니다.

**[추론]**
- 실내와 핀은 90° 돌아간 CAD 도면 좌표에서 모델링한 뒤 −90°로 놓았습니다.
- identity 그룹은 “제자리에서 묶기(Make Group)”로 만든 것입니다. 정의 좌표가 부모 좌표와 같습니다.

**[권장]**
- 회전 프레임마다 최상위 그룹 하나를 두고, 회전은 그 그룹 변환에만 둡니다.
- 하위 그룹은 identity로 유지합니다. 회전 값은 이름이나 설명에 기록합니다(예: `INT-1F (rot −90°)`).

## 규칙 8 — 정의 원점은 기준면(좌판·상판·바닥 모서리)에 둠
<!-- sion-guide id="definition-origin" order="9" kind="pattern" applies_to="furniture,column,person,imported-3d,site-container" tools="sketchup-mcp2.get_component_info,hueflow.execute_ruby" evidence="def:C1,def:T,def:T2,def:c3#2,def:ch5,def:SO,def:col,def:그룹#16,def:그룹#29,def:Humano4_262,def:학장동 skp.dwg" -->

**[관측]** 정의 bbox 최소점과 원점의 관계(사용 중 정의, `bounds_min`):
- 그룹: 원점 = 최소점 91, 5 m 이내 104, 먼 것 23. 예: `그룹#16` (−5500, 0, 0), `그룹#29` (−6076, 0, 0).
- 컴포넌트: 원점 = 최소점 5, 근처 6, 먼 것 9.
- `ch5`, `c3`, `ch6`, `SO`, `col`은 원점이 최소점 (0,0,0)입니다.
- `C1`은 최소점 z가 −470입니다. 원점이 좌판 높이에 있습니다.
- `T`는 −670, `T2`는 −660입니다. 원점이 상판 밑면에 있습니다.
- `c3#2`는 z가 +100입니다.
- 가져온 사람(`Humano4_*`)과 `Component#28`(최소점 (−161, 219, −2221)) 등은 원점이 멉니다.
- 모든 정의의 `insertion_point`는 (0,0,0)입니다.

**[추론]**
- 의자와 테이블은 좌판·상판 면을 먼저 그리고 그 높이를 원점으로 삼았습니다.
- 그룹은 대부분 “제자리에서 묶기”로 만들었습니다. 그래서 정의 원점이 월드 좌표의 흔적을 가집니다.

**[권장]**
- 배치용 컴포넌트는 원점을 **바닥 접점의 모서리나 중심**에 둡니다(`col`, `ch5` 방식).
- 가져온 모델은 원점을 다시 잡습니다(`Change Axes`). 이 작업은 사람 확인 후에 합니다.

## 규칙 9 — 레벨 적층: 층 컨테이너의 Z 원점 = 층 바닥 레벨
<!-- sion-guide id="level-stacking" order="10" kind="pattern" applies_to="building,floor-slab,roof,terrain,paving,exterior-stair" tools="hueflow.execute_ruby,sketchup-mcp2.list_components" evidence="obj:511546,obj:125433,obj:1458557,obj:4577802,obj:1245541,obj:1245859,def:그룹#205,def:그룹#207" -->

**[관측]**
- 인스턴스 월드 최소 Z 군집(본동): 5000 (213개), 10220 (154개), 10200 (12개), 지붕 13363–13830.
- 대지 레벨: −11660, −9500, −6000, −5500, −5000, −2500 (8개), 0 (8개), 4500.
- 원점 Z
  - 실내 `그룹#105`·`새 블럭.dwg`·`그룹#40`·`그룹#65`·`col`: 5000
  - 본동 `그룹#201`: 4800, 그 하위 `그룹#202`: +5300(로컬)
  - 지형 `그룹#39`·`그룹#102`: 10200
  - 계단·옹벽 `그룹#18`·`그룹#34`: −2500

**[추론]**
- 1층 바닥 FL=5000, 2층 FL≈10200–10220입니다.
- 층별로 묶은 것은 `그룹#202` 아래 `그룹#203`(1층 천장)·`그룹#205`(2층)·`그룹#207`(지붕)뿐입니다. 나머지 부재는 부위별 그룹에 레벨이 섞여 있습니다.

**[권장]**
- 층 컨테이너(`BLDG-1F`, `BLDG-2F`, `BLDG-RF`)를 만들고 그 원점 Z를 FL로 둡니다.
- 하위 부재는 컨테이너 기준 로컬 Z=0에서 시작하게 합니다.

## 규칙 10 — 붙임(glue)·개구부 자르기는 거의 쓰지 않음
<!-- sion-guide id="glue-and-cut" order="11" kind="pattern" applies_to="floor-slab,door,window-louver,curtain-wall" tools="hueflow.execute_ruby,sketchup-mcp2.get_component_info" evidence="occ:511546.4577802.4361372.4238021,def:그룹#133,def:그룹#203,def:Niraj" -->

**[관측]**
- 면에 붙은 인스턴스는 `그룹#133` 하나뿐입니다(1층 천장 `그룹#203` 안 접힌 콘크리트 천장, glued_to Face).
- `cuts_opening=true`인 정의도 `그룹#133` 하나입니다.
- 문·창·커튼월은 모두 붙임 없이 독립 그룹입니다.
- 미사용 `Niraj`만 `always_face_camera`를 가집니다.
- 나머지 컴포넌트는 `cuts_opening=false`, `snapto=0`입니다.

**[추론]** 개구부는 벽 그룹 형상을 직접 비워서 만들었습니다. 자르는 컴포넌트에 의존하지 않았습니다.

**[권장]**
- 반복되는 창·문은 `cuts_opening` 컴포넌트로 만들어 벽 면에 붙입니다.
- 단, 그룹 안 벽에는 같은 컨텍스트에 놓아야 잘립니다. 이 점을 검증 단계에서 확인합니다.

## 규칙 11 — 작업용 표식(@0818변경, 빨간 표식)과 미정리 상태
<!-- sion-guide id="working-markup" order="12" kind="pattern" applies_to="marker,terrain,annotation,unused-definition,cad-reference" tools="hueflow.list_layers,hueflow.list_components,hueflow.execute_ruby" evidence="obj:4580639,obj:4580640,obj:1249504,obj:1249528,tag:@0818변경,tag:@LOCK,mat:<auto>2,def:그룹#42,def:그룹#44,def:그룹#12" -->

**[관측]**
- 동측 조경 `그룹#38` 안에 변경 표시 면 `그룹#42`·`그룹#44`가 있습니다. 재질은 `<auto>2`(`@0818변경` 태그 색과 같음)이고, `그룹#42` 안 모서리 4개가 `@0818변경` 태그에 있습니다.
- 최상위 빨간 표식 `그룹#12`가 2개 있습니다.
- `@LOCK`은 미사용 CAD 안 `장애인주차` 인스턴스 태그로만 남아 있습니다.
- 잠금과 숨김은 0개이고, 미사용 정의 59개는 purge되지 않았습니다.

**[추론]**
- 8/18 변경안은 CAD 변경 레이어 색으로 칠한 별도 그룹으로 표시하고 기존 형상 위에 겹쳐 두었습니다.
- 빨간 그룹은 회의용 위치 표식입니다.

**[권장]**
- 작업용 그룹은 `WIP-날짜-내용` 이름과 `WIP` 태그를 붙입니다.
- 확정되면 원래 그룹에 합치고 표식을 지웁니다. 지우는 것은 사람이 결정합니다.

## 1단계 — 현황 읽기와 작업 단위 설정
<!-- sion-guide id="step-inspect" order="13" kind="step" implements="top-split-by-part,working-markup" applies_to="site-container,building,unused-definition" tools="hueflow.get_model_info,sketchup-mcp2.get_model_info,hueflow.list_entities,hueflow.list_layers,sketchup-mcp2.list_components" evidence="model:0914,grouping-probe:nodes" -->

- **입력**: 열린 모델. 단위는 mm여야 합니다. 이 모델은 `LengthUnit` mm입니다.
- **판단 규칙**
  - 저장 안 된 변경(`model.modified?`)이 있으면 읽기만 합니다.
  - `active_path`가 비어 있지 않으면, 편집 컨텍스트 안이라는 것을 먼저 보고합니다.
- **작업**: 아무것도 만들지 않습니다. 최상위 인스턴스 목록을 보고 작업 단위(대지/본동/실내/조경)를 정합니다.
- **MCP**
  - `hueflow.get_model_info`
  - `hueflow.list_entities`
  - `hueflow.execute_ruby`에 읽기 전용 Ruby를 넘깁니다. `scripts/sketchup/grouping_probe.rb`를 그대로 실행합니다.
- **검증**: 깊이 히스토그램과 최상위 수를 기록합니다(이 모델 0:18 … 6:82). `locked`/`hidden`/glued 수를 기록합니다.
- **근거 [관측]**: 프로브 `model_modified=true`, `active_path=[]`.

## 2단계 — CAD를 컴포넌트로 가져와 대지 프레임 설정
<!-- sion-guide id="step-cad-host" order="14" kind="step" implements="cad-host-nesting,rotated-frames" applies_to="cad-reference,site-container" tools="hueflow.execute_ruby,hueflow.rotate_entity,sketchup-mcp2.get_component_info" evidence="obj:30598,def:학장동 skp.dwg,tag:도로계획" -->

- **입력**: 대지 DWG(이 모델은 `학장동 skp.dwg`).
- **판단 규칙**
  - DWG는 하나의 컴포넌트로 가져옵니다.
  - 도면 북쪽이 모델 축과 다르면 컴포넌트 변환에만 회전을 줍니다(이 모델 4.09°).
- **작업**
  - [관측] 이 모델은 대지 3D 그룹을 CAD 정의 **안**에 두었습니다.
  - [권장] 새 모델은 CAD를 `CAD-참조` 태그와 잠금으로 두고 3D는 밖에 둡니다.
- **MCP / Ruby (mm)**
  ```ruby
  m = Sketchup.active_model
  cad = m.entities.grep(Sketchup::ComponentInstance).find { |i| i.definition.name.end_with?('.dwg') }
  # 회전·원점 확인만 (읽기)
  t = cad.transformation; [t.origin.to_a.map(&:to_mm), Math.atan2(t.xaxis.y, t.xaxis.x).radians]
  ```
  - [권장] 새 모델에서 회전을 줄 때만 사용합니다:
    `cad.transform!(Geom::Transformation.rotation(cad.transformation.origin, Z_AXIS, 4.09.degrees))`
- **검증**: CAD 컴포넌트 회전 각도가 대지 계열 그룹 회전과 같은지 확인합니다(이 모델 모두 4.09°).
- **근거**: `학장동 skp.dwg` 원점 (3792.6, −6896.1, 0), `도로계획` 모서리 88개.

## 3단계 — CAD 선 위에 대지 부위 면 작성 후 부위별 그룹
<!-- sion-guide id="step-site-parts" order="15" kind="step" implements="cad-host-nesting,tags-on-raw-geometry" applies_to="retaining-wall,paving,road-plan-surface,terrain" tools="hueflow.create_face,hueflow.push_pull,hueflow.create_group,hueflow.execute_ruby" evidence="def:그룹#1,def:그룹#5,def:그룹#6,def:그룹#7,def:그룹#14,def:그룹#30,def:그룹#35,tag:도로계획" -->

- **입력**: CAD 도로계획·옹벽 선, 레벨(−9500, −6000, −5000, −2500, 0 등).
- **판단 규칙**
  - 옹벽·포장·도로면처럼 **부위 하나 = 그룹 하나**로 묶습니다.
  - 레벨이 다른 면은 같은 부위면 같은 그룹에 둡니다.
- **작업**
  - CAD 선을 따라 면을 만들고 Push/Pull로 높이를 줍니다. 그 다음 선택 → 그룹으로 묶습니다.
  - [관측] 이름과 태그는 기본값(`Layer0`)입니다. 형상 모서리는 `도로계획` 태그를 물려받습니다.
- **MCP / Ruby (mm)**
  ```ruby
  ents = Sketchup.active_model.active_entities
  g = ents.add_group; f = g.entities.add_face([0,0,0].map(&:mm), [6000.mm,0,0], [6000.mm,300.mm,0], [0,300.mm,0])
  f.reverse! if f.normal.z < 0; f.pushpull(2500.mm)   # 옹벽 높이 예시는 [권장] 값
  g.name = 'SITE-RW-01'; l0 = Sketchup.active_model.layers[0]; g.entities.each { |e| e.layer = l0 }
  ```
- **검증**
  - 각 부위 그룹 안 `Layer0`이 아닌 모서리 수를 셉니다(이 모델 `그룹#6` 68, `그룹#14` 32 …).
  - [권장] 새 모델은 0이어야 합니다.
- **근거**: `학장동 skp.dwg` 하위 그룹 8개.

## 4단계 — CAD 밖 대지 조립체(외부계단·옹벽·조경·지형·포장)
<!-- sion-guide id="step-site-assemblies" order="16" kind="step" implements="top-split-by-part,nest-by-assembly,rotated-frames" applies_to="exterior-stair,handrail,wall,retaining-wall,terrain,paving" tools="hueflow.create_group,hueflow.move_entity,hueflow.rotate_entity,hueflow.execute_ruby" evidence="obj:47944,obj:90359,obj:125087,obj:125433,obj:1245541,obj:1245859,def:그룹#18,def:그룹#34" -->

- **입력**: 2·3단계의 대지 프레임과 레벨.
- **판단 규칙**
  - 조립체(계단 + 난간 + 측벽)는 **최상위 그룹 하나**로 묶습니다. 하위에 부재 그룹을 둡니다.
  - 덩어리 하나인 부위(옹벽 `그룹#34`, 면 681개)는 말단 그룹 하나로 둡니다.
- **작업**
  - `그룹#18`: 계단 `그룹#19`(`Raise`)·`그룹#23`, 난간 `그룹36#1`·`그룹53#1`(`Handrail`), 벽 `그룹#21`·`#24`·`#37`·`#166`을 하위로 둡니다. 그 자체에 모서리 95와 면 30이 있는 혼합형입니다.
  - 동측 조경 `그룹#38`은 컨테이너로 두고, 변경 면 `그룹#42`·`그룹#44`를 하위로 둡니다.
  - 지형 `그룹#39`·`그룹#102`는 Z=10200에 둡니다.
- **MCP**
  - `hueflow.create_group`(선택 묶기)
  - 회전 맞춤에 `hueflow.rotate_entity`(축 Z, 4.09°)
  - Ruby로 하위를 묶을 때: `parent = ents.add_group(sel.to_a)` (선택 엔터티를 새 그룹으로 이동)
- **검증**
  - 대지 조립체 회전 = CAD 회전(4.09°)인지 봅니다.
  - 원점 Z가 레벨과 같은지 봅니다(`그룹#18`·`#34` −2500).
- **근거 [관측]**: 최상위 pid 순서 학장동 30598 < `그룹#18` 47944 < `그룹#34` 90359 < `그룹#38` 125087 < `그룹#40` 125433. [추론] 대지를 먼저 만들었습니다.

## 5단계 — 본동 컨테이너와 층별 슬래브·천장·지붕 묶음
<!-- sion-guide id="step-building-container" order="17" kind="step" implements="top-split-by-part,nest-by-assembly,level-stacking" applies_to="building,floor-slab,roof,beam" tools="hueflow.create_group,hueflow.create_box,hueflow.push_pull,hueflow.execute_ruby" evidence="obj:511546,obj:4577802,def:그룹#202,def:그룹#203,def:그룹#205,def:그룹#207,def:그룹#222,obj:1171922" -->

- **입력**: FL 5000(1층), 10200–10220(2층), 지붕 13363–13830.
- **판단 규칙**
  - 본동 전체를 최상위 컨테이너 하나(`그룹#201`, 0°, Z 4800)로 둡니다.
  - 수평 부재(천장·바닥·지붕)는 하위 컨테이너(`그룹#202`) 아래 층별 그룹으로 나눕니다.
- **작업**
  - `그룹#202` → `그룹#203`(1층 천장), `그룹#205`(2층 바닥 + 2층 가구), `그룹#207`(지붕 3개), `그룹#222`.
  - 보 `그룹#89`는 최상위에 별도로 남아 있습니다 [관측]. 본동 보 `그룹#225`는 본동 안에 있습니다.
- **MCP / Ruby (mm)**
  ```ruby
  b = Sketchup.active_model.entities.add_group; b.name = 'BLDG'
  b.transform!(Geom::Transformation.translation([0, 0, 4800.mm]))
  rf = b.entities.add_group; rf.name = 'BLDG-SLABS'   # 하위 컨테이너는 형상 없이
  ```
- **검증**
  - `그룹#202`처럼 컨테이너의 직접 형상 수가 0인지 확인합니다.
  - 층 그룹 최소 Z가 FL 군집과 맞는지 확인합니다.
- **근거**: `그룹#202` 직접 형상 0 / 하위 4.

## 6단계 — 외피·별동·개구부를 하위 조립체로 깊게 묶기
<!-- sion-guide id="step-envelope-assemblies" order="18" kind="step" implements="nest-by-assembly,glue-and-cut,rotated-frames" applies_to="wall,curtain-wall,glass-railing,door,window-louver,building" tools="hueflow.execute_ruby,hueflow.create_group,sketchup-mcp2.create_component" evidence="obj:4577805,obj:4577809,obj:4577801,def:그룹#129,def:그룹#161,def:그룹167#1,occ:511546.4577805.4164146.4164144.4163927.4163488.4163456,occ:511546.4577801.4204624.4204575.4204512.4204509.4204480" -->

- **입력**: 5단계 본동 컨테이너.
- **판단 규칙**
  - 벽·커튼월·유리난간은 본동 직속 하위 그룹으로 둡니다.
  - 별동은 그 자체를 컨테이너(`그룹#161`, `그룹#217`)로 둡니다.
  - 루버·문처럼 살이 반복되는 부재는 identity 하위 그룹 세트로 묶습니다.
- **작업**
  - 루버 살 24개(`그룹169#1`–`그룹192#1`)를 identity로 `그룹167#1`에 넣습니다.
  - 루버 세트를 창 → 외피 → 별동으로 차례로 묶습니다(깊이 6).
  - 미닫이문 `그룹#257`도 커튼월 `그룹#129` 아래 깊이 6에 있습니다.
- **MCP / Ruby (mm)** 루버 살 배열 [권장 예시, 간격·치수는 설계값으로 바꿀 것]:
  ```ruby
  set = parent.entities.add_group; set.name = 'LOUVER-SET'
  slat = set.entities.add_group; slat.entities.add_face(...).pushpull(...)
  (1...n).each { |k| set.entities.add_instance(slat.definition, Geom::Transformation.translation([0, 0, k * pitch.mm])) }
  ```
- **검증**
  - 하위 깊이 ≤ 6인지 확인합니다.
  - 반복 살이 같은 정의를 공유하는지 봅니다(`definition.count_instances`).
  - 붙임 / `cuts_opening`이 의도대로인지 확인합니다.
- **근거**: 깊이 6 사슬 2개.

## 7단계 — 반복 부재: 컴포넌트 정의 또는 그룹 복제, 반전 복사
<!-- sion-guide id="step-repeats" order="19" kind="step" implements="component-for-repeats,definition-origin,default-naming" applies_to="furniture,column,handrail,tree" tools="sketchup-mcp2.create_component,sketchup-mcp2.find_components,sketchup-mcp2.transform_component,hueflow.place_component,hueflow.execute_ruby" evidence="def:C1,def:ch5,def:col,def:그룹#57,def:그룹#98,def:그룹#68,occ:511546.4577802.4361373.4360622.4360577" -->

- **입력**: 반복 부재 형상 하나.
- **판단 규칙**
  - 이름 붙여 관리할 부재(가구·기둥)는 컴포넌트로 만듭니다.
  - 현장에서 복사만 하는 부재(파이프·살·나무)는 그룹 복사(정의 공유)로 둡니다.
  - 대칭 부재는 축척 −1로 반전 복사합니다.
- **작업**
  - 원점은 기준면에 둡니다(의자 `C1` 좌판, 테이블 `T` 상판 밑면 [관측]). 짧은 코드 이름을 붙입니다.
  - 파이프 `그룹#57`(`D=15 mm`)은 29개씩 `그룹#68`에 담고, `그룹#68`을 2번 배치합니다 [관측].
- **MCP**
  - `sketchup-mcp2.create_component`
  - `hueflow.place_component`
  - `sketchup-mcp2.transform_component`
  - 반전은 Ruby로 합니다: `inst.transform!(Geom::Transformation.scaling(inst.bounds.center, -1, 1, 1))`
- **검증**
  - 인스턴스 수를 셉니다(`C1` 47, `ch5` 11 …).
  - 반전 인스턴스(`(t.xaxis * t.yaxis) % t.zaxis < 0`, `t = inst.transformation`)를 기록합니다. 이 모델은 18개입니다.
- **근거**: `그룹#98` ×11 반전, 의자 `ch5` 안.

## 8단계 — 1층 실내를 회전 프레임 컨테이너로 분리
<!-- sion-guide id="step-interior" order="20" kind="step" implements="rotated-frames,top-split-by-part,component-for-repeats" applies_to="furniture,counter-millwork,interior-stair,curtain-wall,building" tools="hueflow.create_group,hueflow.rotate_entity,hueflow.place_component,hueflow.execute_ruby" evidence="obj:1458557,obj:4905257,def:그룹#160,def:C1,def:T,def:SO,def:T2,def:그룹#111" -->

- **입력**: 90° 돌아간 실내 평면 CAD, FL 5000.
- **판단 규칙**
  - 도면 축으로 그리고, 최상위 컨테이너 하나에 −90° 회전을 줍니다.
  - 실내 요소는 그 안의 작업 그룹(`그룹#160`) 하나에 모읍니다.
- **작업**
  - `그룹#105`(원점 (808.7, 54872.7, 5000), −90°) → `그룹#160`.
  - `그룹#160` 안에는 카운터 4, 실내계단 `그룹#111`, 커튼월 프레임 `그룹#46`, 가구 컴포넌트 68개가 있습니다. 직접 형상(모서리 58, 면 25)이 섞인 혼합형입니다.
- **MCP / Ruby (mm)**
  ```ruby
  int = Sketchup.active_model.entities.add_group; int.name = 'INT-1F (rot -90°)'
  int.transform!(Geom::Transformation.rotation(ORIGIN, Z_AXIS, -90.degrees))
  int.transform!(Geom::Transformation.translation([808.7.mm, 54872.7.mm, 5000.mm]))  # 이 모델 원점
  ```
- **검증**
  - 실내 가구 월드 최소 Z = 5000 군집인지 확인합니다.
  - 회전 컨테이너 하위가 identity 또는 Z 회전만 가졌는지 봅니다.
- **근거**: 최상위 pid `그룹#105` 1458557. [추론] 본동·수목보다 늦게 추가됐습니다.

## 9단계 — 2층 핀(외부 루버)을 가져온 블록으로 배치
<!-- sion-guide id="step-fins" order="21" kind="step" implements="rotated-frames,cad-host-nesting" applies_to="curtain-wall,cad-reference" tools="hueflow.place_component,hueflow.rotate_entity,sketchup-mcp2.get_component_info" evidence="obj:1181414,obj:4915226,def:새 블럭.dwg,def:그룹#54" -->

- **입력**: 핀 블록 DWG(`새 블럭.dwg`).
- **판단 규칙**: 블록 컴포넌트 안에 3D 그룹 하나(`그룹#54`)만 두고, 블록 인스턴스에 −90°를 줍니다.
- **작업**
  - [관측] 원점 (60713.7, 44600, 5000), 하위 `그룹#54` 원점 (200, 2350, 5200).
  - [권장] 이름을 `BLDG-2F-FIN`으로 바꾸고, 블록 정의 이름에서 `.dwg`를 빼서 출처를 설명에 적습니다.
- **MCP**: `sketchup-mcp2.get_component_info`로 정의를 확인합니다. 배치는 `hueflow.place_component` + `hueflow.rotate_entity`(−90°).
- **검증**: 핀 정의의 직접 형상이 0이고 하위가 그룹 1개인지 확인합니다.
- **근거**: `새 블럭.dwg` 정의 최소점 (200, 2350, 5200).

## 10단계 — 수목·화분·사람·기둥 배치
<!-- sion-guide id="step-landscape-people" order="22" kind="step" implements="component-for-repeats,tags-on-raw-geometry,definition-origin" applies_to="tree,planter,person,column,imported-3d" tools="hueflow.place_component,sketchup-mcp2.transform_component,hueflow.execute_ruby" evidence="obj:800070,def:그룹#74,def:Component#28,tag:Trees 3D,def:그룹#62,def:Humano4_262,def:col,obj:2004749" -->

- **입력**: 나무 3D 모델(`Component#28`, `Trees 3D` 태그), 사람 모델(`Humano4_*`), 기둥 `col`.
- **판단 규칙**
  - 나무는 그룹 `그룹#74`로 감쌉니다. 비균일 축척 0.4271/0.457 또는 0.3203으로 크기를 맞춥니다.
  - 수목 묶음 `그룹#65`(11 + `그룹#53`·`#56`)는 최상위에 둡니다.
  - 화분 안 나무(`그룹#62`·`#72`·`#73`)는 본동 안에 둡니다.
  - 기둥 `col` 4개는 최상위 독립 컴포넌트입니다(X 70273.7, Z 5000).
- **작업**: 사람은 본동 하위에 그룹이나 컴포넌트로 둡니다(`Component18`, `그룹#110`·`#139` 반전 등).
- **MCP**: `hueflow.place_component`, `sketchup-mcp2.transform_component`(축척·회전).
- **검증**
  - `Trees 3D` 태그가 나무 정의 내부와 `Component#28` 인스턴스에만 있는지 확인합니다.
  - 축척이 의도값인지 확인합니다.
- **근거**: `Component#28` 16배치, 모두 `Trees 3D`.

## 11단계 — 회의용 변경안·표식 그룹 겹쳐 두기
<!-- sion-guide id="step-markup" order="23" kind="step" implements="working-markup" applies_to="marker,terrain,annotation" tools="hueflow.create_group,hueflow.execute_ruby,hueflow.list_layers" evidence="obj:4580639,obj:4580640,obj:1249504,obj:1249528,tag:@0818변경,mat:<auto>2" -->

- **입력**: 변경 지시(8/18 변경), 회의 위치.
- **판단 규칙**: 기존 형상은 고치지 않습니다. 변경 범위를 **별도 그룹**으로 겹쳐 그리고, 변경 레이어 색 재질을 칠합니다.
- **작업**
  - [관측] `그룹#42`·`그룹#44`(`<auto>2`)를 동측 조경 `그룹#38` 아래에 둡니다.
  - [관측] 빨간 `그룹#12` 2개를 최상위에 둡니다(하나는 −84.5° 회전, Z 12364.3).
  - [권장] `WIP-0818-동측조경` 이름과 `WIP` 태그를 붙입니다.
- **MCP / Ruby (mm)**
  ```ruby
  m = Sketchup.active_model; wip = m.layers['WIP'] || m.layers.add('WIP')
  g = m.active_entities.add_group; g.name = 'WIP-0818-동측조경'; g.layer = wip
  ```
- **검증**: 작업용 그룹 목록을 회의 후 사람에게 확인받습니다. 자동 삭제는 하지 않습니다.
- **근거**: `@0818변경` 태그 모서리 4(`그룹#42`).

## 12단계 — 그룹화 검증과 정리(사람 확인 후)
<!-- sion-guide id="step-verify-cleanup" order="24" kind="step" implements="tags-on-raw-geometry,nest-by-assembly,default-naming,glue-and-cut,working-markup" applies_to="unused-definition,cad-reference,building,site-container" tools="hueflow.execute_ruby,hueflow.list_components,sketchup-mcp2.list_components,sketchup-mcp2.list_layers" evidence="grouping-probe:definitions,def:그룹#160,def:그룹#201,occ:511546.4577802.4361372.4238021,tag:@LOCK" -->

- **입력**: 완성 모델.
- **판단 규칙**: 아래 항목을 읽기 전용으로 점검합니다. purge, 삭제, 저장은 사람 승인 후에만 합니다.
- **점검 항목**
  1. 최대 깊이와 깊이별 수.
  2. `Layer0`이 아닌 인스턴스와 직접 형상(정의별).
  3. 혼합 정의(형상 + 하위) 목록.
  4. 기본 이름 그룹 수.
  5. 반전·비균일 축척 인스턴스.
  6. glued / `cuts_opening`.
  7. locked / hidden.
  8. 미사용 정의 수(이 모델 59).
- **MCP / Ruby (읽기 전용, mm)**
  ```ruby
  walk = ->(ents, d, out) { ents.each { |e| next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
    out << [d, e.definition.name, e.layer.name]; walk.(e.definition.entities, d + 1, out) } ; out }
  rows = walk.(Sketchup.active_model.entities, 0, [])
  { max_depth: rows.map(&:first).max, non_layer0: rows.count { |r| r[2] != 'Layer0' } }
  ```
- **검증 기준 [권장]**
  - 최대 깊이 ≤ 5.
  - 내부 형상의 CAD 태그 0.
  - 컨테이너 직접 형상 0.
  - 최상위·2단계 이름 100% 지정.
  - 작업용(WIP) 그룹 0 또는 승인 목록과 일치.
- **근거 [관측]**: 이 모델은 깊이 6, CAD 태그 형상 21개 정의, 혼합 정의 55, 기본 이름 228, 미사용 59, glued 1(`그룹#133`).
