# SketchUp 건축·대지 모델링 지침 (근거 모델: 0914_담당미팅.skp)

이 문서는 SketchUp 2025에 열려 있던 `0914_담당미팅.skp`(경사 대지 위 계단식 주차장 + 2층 카페 본동 + 별동 +
조경)를 **읽기 전용**으로 추출한 덤프(`data/sources/sketchup/0914-meeting/model_dump.json`)와 형상 프로브
(`geometry_probe.json`)에서 만든 지침입니다. `##` 절 하나가 GraphRAG 청크 하나(`sketchup:guide:<id>`)가 되고,
절 머리의 `sion-guide` 주석이 객체 클래스(`sketchup:class:*`)·MCP 도구·근거 객체로 가는 엣지를 만듭니다.

표기: **[관측]** 덤프·프로브에서 바로 읽은 사실(수치는 mm, 월드 좌표), **[추론]** 사실에서 해석한 내용(검토 전),
**[권장]** 이 모델에 없거나 부족해서 일반 SketchUp 실무 원칙으로 덧붙인 규칙. 모델에 없는 치수나 객체는 만들지 않았습니다.

## 지침 사용법과 모델 개요
<!-- sion-guide id="overview" order="1" kind="index" applies_to="site-container,building,terrain" tools="hueflow.get_model_info,sketchup-mcp2.get_model_info" evidence="model:,obj:30598,obj:511546" -->

**[관측] 모델 개요**
- 파일 `0914_담당미팅.skp`, SketchUp 25.0.634, 저장되지 않은 변경이 있는 상태에서 추출(modified=true).
- 전체 범위 100,698.6 × 64,115.9 × 27,110.3 mm (최소점 866.1, -7,783.1, -11,660.0 / 최대점 101,564.6, 56,332.9, 15,450.3).
- 최상위 엔터티 19개: 그룹 12, 컴포넌트 인스턴스 6, 단면 평면 1. 정의 297개(그룹 정의 229, 컴포넌트 정의 68), 그중 루트에서 도달하는 정의 238개, 도달하지 않는 정의 59개(인스턴스 0개인 정의 38개 포함).
- 태그 49개, 재질 130개, 장면 3개, 스타일 3개. 정의 단위 합계: 면 128,329, 모서리 427,343, 구성점 108. 텍스트·치수 엔터티 0개.
- 최상위 구성(월드 최소점·크기):
  - `학장동 skp.dwg`(컴포넌트, pid 30598): 대지 전체. 97,855.7 × 64,115.9 × 21,994.9, Z축 4.09° 회전.
  - `그룹#18`(pid 47944): 외부계단 조립체, z -2,500부터.
  - `그룹#34`(pid 90359): 트래버틴 옹벽·경사 매스, z -11,660부터(모델 최저점).
  - `그룹#38`, `그룹#39`, `그룹#102`: 동측 조경 경사면. `그룹#40`: z 5,000 수평 바닥면(1,069.5 m²).
  - `그룹#201`(pid 511546): 카페 본동과 별동 일체 컨테이너, z 4,800~15,450.
  - `그룹#105`(pid 1458557): 1층 실내(가구·카운터·계단·커튼월 프레임).
  - `새 블럭.dwg`(pid 1181414): 2층 수직 핀/멀리언(추정), z 10,200.
  - `그룹#65`: 수목 13그루(`그룹#74` ×11 + 같은 형상 사본 `그룹#53`·`그룹#56`), `col` ×4: 원형 기둥, `그룹#89`: 보, `그룹#12` ×2: 빨간 표식 판.

**[추론]** 대지(서측, x ≈ 0~60 m)는 계단식 주차장과 옹벽, 건물(동측, x ≈ 57~101 m)은 1층 바닥 +5,000 레벨에 놓인
2층 카페입니다(렌더 장면 3개 모두 카페 실내).

**사용법**: 에이전트는 (1) 그릴 대상의 클래스를 `sketchup:class:*`에서 찾고, (2) `REFERENCES/applies_to_class`로
연결된 지침 청크를 읽고, (3) `IMPLEMENTS/classified_as`로 연결된 이 모델의 실제 정의(크기·재질·레벨)를 예시로
가져온 뒤, (4) `mcp-execution` 절의 절차로 실행합니다. 분류 엣지는 모두 추론 후보(unverified)이므로 수치는
정의 노드(사실)에서 다시 확인합니다.

## 표준 모델링 작업 순서
<!-- sion-guide id="workflow" order="2" kind="workflow" after="overview" applies_to="site-container,terrain,retaining-wall,parking-deck,building,floor-slab,wall,curtain-wall,roof,furniture,tree" tools="hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="model:" -->

**[추론] 이 모델이 만들어진 순서**(계층과 이름에서 읽은 흐름)
1. CAD 배치도(`학장동 skp.dwg`)와 평면도(`그룹#107` 등)를 DWG로 가져옴 → 2D 선을 기준으로 대지 3D화.
2. 대지: 기존 지형(`기존조경` 재질) → 계획 지형(`[Vegetation Grass]`) → 옹벽(트래버틴·벽돌) → 주차 데크·경사로 → 외부계단·난간.
3. 건물: 1층 바닥 레벨 +5,000에 매스 배치 → 바닥/천장(접힌 천장) → 기둥·보 → 커튼월·문 → 2층(+10,200) 외피 → 지붕(+13,363 이상).
4. 실내: 1층 가구 세트(`그룹#160`), 카운터, 내부계단 → 2층 가구(`그룹#205` 하위).
5. 조경·인물: 플랜터와 수목, 인물 피겨로 스케일 표현.
6. 장면 3개(실내 투시도)와 단면 1개로 검토 화면 구성.

**[권장] 새 모델 작업 순서**
1. 템플릿·단위(mm) 확인 → 2. CAD 가져오기·정리(원점 이동, 레이어 정리) → 3. 레벨 체계 결정(대지 기준 0, 1층 FL 등)
→ 4. 대지·지형 → 5. 옹벽·포장·주차·외부계단 → 6. 건물 매스(동별 그룹) → 7. 슬래브·기둥·보 → 8. 벽·커튼월·창호
→ 9. 지붕 → 10. 내부계단·난간 → 11. 붙박이 가구·가구 → 12. 조경·인물 → 13. 재질 → 14. 장면·스타일·단면
→ 15. 정리(미사용 정의 확인, 사람 승인 후 purge) → 16. QA.
각 단계는 별도 최상위 그룹으로 만들고, 단계가 끝날 때마다 `find_components`/덤프로 크기와 레벨을 확인합니다.

## 단위·원점·축·위치
<!-- sion-guide id="units-origin" order="3" after="workflow" applies_to="site-container,building" tools="hueflow.get_model_info,hueflow.execute_ruby,sketchup-mcp2.get_model_info" evidence="model:,obj:30598,obj:1181414" -->

**[관측]**
- 단위 mm, 십진 표기, 정밀도 0자리, 길이 스냅 켬(1 mm), 각도 스냅 15°, 면적 m²(소수 2자리), 체적 m³(소수 2자리).
- 모델 축 원점 (0,0,0), X축 (1,0,0) 기본값. 그림자 위치 서울/한국(위도 37.5, 경도 127.0, UTC+9), 그림자 표시 꺼짐.
- 지오레퍼런스 사용 안 함(`UsesGeoReferencing=false`). 모델 속성의 GeoReference 위·경도(40.018, -105.242)는 기본 템플릿 값이며 실제 대지와 무관.
- 대지 CAD 컴포넌트 `학장동 skp.dwg`는 Z축 4.09° 회전, `새 블럭.dwg`는 -90° 회전 배치. 모델 범위 최소점 x는 866.1로 원점 가까이에 있다.
- 미사용 CAD 정의 `인테리어`·`우리필지배경`·`새 블럭.dwg#1`의 정의 범위는 각각 약 10.9 km, 11.1 km, 13.7 km(CAD 원좌표 그대로).

**[권장]**
- 새 모델은 mm 템플릿으로 시작하고 `get_model_info`로 단위가 mm인지 먼저 확인합니다. Ruby에서는 숫자에 반드시 `.mm`를 붙입니다(내부 단위는 inch).
- CAD 원좌표가 수 km 떨어져 있으면 원점 근처로 옮겨서 가져옵니다(정밀도·카메라 클리핑 문제 예방). 이 모델에서 실제로 쓰인 객체는 원점 근처로 옮겨진 상태입니다.
- 건물 축이 대지 CAD와 어긋나면 이 모델처럼 **CAD 컴포넌트를 회전**시키고 건물은 모델 축에 맞춥니다.
- 위치(지리 정보)는 실제 대지로 설정합니다. 일조 검토가 필요하면 지오레퍼런스를 넣고, 아니면 그림자 위치만 맞춥니다.

## CAD(DWG) 가져오기와 정리
<!-- sion-guide id="cad-import" order="4" after="units-origin" applies_to="cad-reference,site-container,road-plan-surface,annotation,parking-stall" tools="hueflow.list_components,hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="def:학장동 skp.dwg,def:그룹#107,def:ZIUM_sheet_architect,def:인테리어,tag:도로계획,mat:<auto>" -->

**[관측]**
- 가져온 CAD는 정의 이름이 `.dwg`로 끝나는 컴포넌트가 된다: `학장동 skp.dwg`(사용 중), `새 블럭.dwg`(사용 중), `새 블럭.dwg#1`·`새 블럭.dwg#2`·`f2.dwg`·`ST.dwg`(미사용).
- 평면도 원본 2D는 미사용 그룹 `그룹#107`에 남아 있다: CAD 태그 37종에 모서리 82,664개(DVM_INDOOR 53,495, FUR 4,741, @stair 4,515, @LOCK 3,287 …), 문 기호 블록 `*U20` 48개.
- 도곽 `ZIUM_sheet_architect` 84,000 × 59,400(A1 840×594의 100배 → 1:100 도곽으로 추정), A-FORM·Layer 1·Defpoints 태그.
- CAD 블록 이름 `*U20`, `*U21`, `A$Ce0c0742d`, `A$C2BE44C31`(익명/동적 블록 이름이 그대로 정의 이름이 됨).
- CAD 레이어 색에서 재질 `<auto>`, `<auto>1` … `<auto>27`(28개)이 자동 생성되어 주로 모서리에 칠해져 있다. 예: `<auto>2`(255,218,113)는 `@0818변경` 태그 색과 같다.
- 살아 있는 3D 형상 안에 남은 CAD 태그는 `도로계획`(대지 그룹들 안 모서리 321개), `XCLINE`(난간 파이프 안 46개), `@0818변경`(4개), `@win`(1개)뿐이다.

**[권장] 처리 절차**
1. DWG는 **컴포넌트로 가져와** 원본 2D를 한 정의에 가둡니다(이 모델 방식). 정의 이름은 `CAD-<도면명>-<날짜>`처럼 출처가 보이게 바꿉니다.
2. 가져온 직후 범위를 확인하고(수 km면 원점 이동), 기준점(대지 모서리 등)을 원점 근처에 맞춥니다.
3. 3D 작업은 CAD 컴포넌트 **위에 별도 그룹**으로 그리고, CAD 선은 참조용으로만 둡니다(이 모델에서 지형·포장 그룹이 CAD 컴포넌트 안에 중첩된 것은 편집 범위를 키우므로 새 모델에서는 피합니다).
4. 3D로 옮긴 뒤 CAD 정의는 `CAD-참조` 계열 태그에 두고 숨기거나, 사람 확인 후 삭제/purge합니다. 에이전트는 purge를 스스로 하지 않습니다.
5. `<auto>` 재질은 CAD 색 잔여물이므로 3D 면에는 의미 있는 재질을 새로 칠합니다.

## 태그(레이어) 체계와 명명 규칙
<!-- sion-guide id="tags" order="5" after="cad-import" applies_to="cad-reference,annotation,tree,handrail,unused-definition" tools="hueflow.list_layers,sketchup-mcp2.list_layers,sketchup-mcp2.create_layer,hueflow.execute_ruby" evidence="tag:Layer0,tag:Trees 3D,tag:@door,tag:@wall,tag:@stair,tag:DIM,tag:LIBFREDO6_TEMP_LAYER" -->

**[관측]**
- 태그 49개, 폴더 없음, 모두 표시 상태. `@` 접두 태그 28개(@win, @stair, @door, @wall, @wall2, @FUR, @DIM, @level, @실명, @실별면적, @지붕선, @마감, @마감2, @주차, @주차대수, @사람, @cen, @INS, @LOCK, @def, @sol, @text, @TEXT_M, @지시선, @ELE, @ARC, @FIN_OUT, @0818변경).
- 그 밖에 CAD 표준형 이름(S-STEEL COLUMN, A-FORM, DIM, Defpoints, WIN, DOOR1, WID, TIT, SYM, SYM_T, FUR, DVM_INDOOR, XCLINE, 002-제작벽체, 입면선, 도로계획, 옹벽, Layer 1)과 SketchUp 측 태그(Layer0, Trees 3D, LIBFREDO6_TEMP_LAYER).
- **3D 객체는 거의 전부 Layer0(Untagged)에 있다.** 살아 있는 정의 안에서 Layer0 외 태그를 쓰는 것은 도로계획·XCLINE·@0818변경·Trees 3D·@win 다섯 개뿐이고, 최상위·2단계 인스턴스 76개는 모두 Layer0.
- 나머지 43개 태그는 미사용 CAD 정의 안에서만 쓰이고, 4개(SYM_T, 옹벽, WID, LIBFREDO6_TEMP_LAYER)는 엔터티가 0개.
- 선 스타일은 `@cen`만 Long-dash dash(중심선), 나머지는 Solid Basic 또는 미지정. `장면 3`은 `LIBFREDO6_TEMP_LAYER`를 숨김.

**[추론]** `@` 접두 + 영문 소문자/한글 이름(@wall, @door, @실명, @지붕선)은 사용자 사무소의 CAD 레이어 규칙이고,
SketchUp 3D 쪽은 태그 대신 **그룹 계층으로 정리**했다. `옹벽` 태그는 만들었지만 쓰지 않았다.

**[권장] 3D 태그 체계**(CAD 규칙과 짝을 맞춤, 기존 이름 재사용 우선)
- 형상은 항상 Layer0에 그리고 **그룹/컴포넌트 인스턴스에만 태그**를 붙입니다.
- 클래스 → 태그 예: 지형 `@3D-대지`, 옹벽 `옹벽`(기존 태그 재사용), 주차 `@주차`, 벽 `@wall`, 문 `@door`, 창·커튼월 `@win`,
  계단 `@stair`, 가구 `@FUR`, 수목 `Trees 3D`(기존), 인물 `@사람`, 치수·주석 `@DIM`, CAD 참조 `CAD-참조`.
- 플러그인 임시 태그(LIBFREDO6_TEMP_LAYER)는 장면에서 숨기고 지우지 않습니다(플러그인이 다시 만듦).
- 태그 생성은 `sketchup-mcp2.create_layer`, 지정은 Ruby `entity.layer = model.layers['@wall']`.

## 그룹·컴포넌트·계층·이름 규칙
<!-- sion-guide id="group-component" order="6" after="tags" applies_to="furniture,column,tree,handrail,person,building" tools="sketchup-mcp2.find_components,sketchup-mcp2.get_component_info,hueflow.list_components,hueflow.place_component,hueflow.execute_ruby" evidence="def:C1,def:col,def:그룹#74,def:그룹#57,def:Component#28,def:ch5" -->

**[관측]**
- 그룹 정의 229개 중 228개가 기본 이름(`그룹#N`, `그룹N#1`)이고 인스턴스 이름도 대부분 비어 있다. 이름이 있는 인스턴스는 플러그인/가져오기 이름(`Raise`, `Handrail`, `D=30 mm`, `D=15 mm`, `Humano4_*`, `CWom0105-…`)뿐.
- 반복 객체는 **짧은 코드 이름의 컴포넌트**: `C1` 의자 ×47, `T` ×8, `T2` ×5, `SO` ×8, `ch5` ×11, `ch6` ×5, `c3` ×6, `c3#2` ×8, `col` 기둥 ×4.
- 그룹도 복사해서 정의를 공유한다: 수목 `그룹#74` 인스턴스 14개, 난간동자 `그룹#57` 29개(난간 반쪽 `그룹#64` 2개가 공유하므로 실제 배치는 58개).
- 공유 그룹 정의를 **비균일 축척**으로 배치: `그룹#74` 14개 중 11개는 축척 (0.4271, 0.4271, 0.457), 3개는 (0.3203, 0.3203, 0.2725 / 0.3527 / 0.3705).
- 중첩 깊이 최대 6(루트=0). `#1`이 붙은 정의(`c3#1`, `T#1`, `새 블럭.dwg#1`)는 같은 이름 정의가 다시 들어오며 생긴 사본.

**[권장]**
- **반복되는 것(가구, 기둥, 수목, 창호 유닛, 인물)은 컴포넌트**, 한 번만 쓰는 것(지형, 옹벽, 슬래브, 지붕)은 그룹.
- 컴포넌트 이름은 `<클래스코드>-<규격>`(예: `CH-450x460x741`, `COL-D480-H4200`)처럼 크기를 담고, 인스턴스 이름은 위치/번호를 담습니다. 기본 `그룹#N` 이름은 남기지 않습니다(에이전트가 `find_components(name=…)`로 찾을 수 없음).
- 계층은 `동(건물) > 층 > 부위 > 부재` 순으로 3~4단계를 넘기지 않습니다. 이 모델처럼 6단계까지 내려가면 편집 범위를 찾기 어렵습니다.
- 공유 정의에 비균일 축척을 주면 형상이 왜곡되므로, 크기가 다른 수목은 축척을 균일하게 하거나 별도 정의로 만듭니다.
- 같은 이름 사본(`#1`)이 생기면 정의 이름을 정리합니다.

## 층·레벨 체계
<!-- sion-guide id="levels" order="7" after="group-component" applies_to="building,floor-slab,interior-stair,exterior-stair,terrain" tools="sketchup-mcp2.list_components,hueflow.execute_ruby" evidence="def:그룹#112,def:그룹#113,def:그룹#19,def:그룹#23,obj:511546,obj:1458557" -->

**[관측]** (월드 z 최소값 분포, 계층 노드 619개 기준)
- z 5,000: 213개(1층 가구·벽·기둥·수목·외부 바닥판). z 10,220: 154개(2층 가구 바닥), z 10,200: 12개(2층 외피·바닥). z 13,363~13,830: 지붕.
- 대지 쪽: z -11,660(최저), -9,500, -6,000, -5,500, -5,000, -2,500(8개), 0(8개), 4,500.
- 내부계단 `그룹#113`: 수평면 31개가 153 mm 간격, 전체 높이 5,200. `그룹#112`: 60 mm 디딤판 쌍이 약 153 mm 간격.
- 외부계단 `그룹#19`: 수평 레벨 14개가 166.7 mm 간격(전체 높이 2,500), `그룹#23`: 수평 레벨 26개가 166.7 mm 간격(전체 높이 4,500).

**[추론]** 1층 FL = +5,000, 2층 FL = +10,200(층고 5,200 = 153 × 34), 2층 마감면 +10,220(가구 바닥). 대지 기준 0과
-2,500, +2,500(외부계단 참), +4,500/+5,000(건물 진입)이 단차입니다.

**[권장]**
- 레벨은 숫자로 고정합니다: 대지 0, 1층 FL +5,000, 2층 FL +10,200처럼 모든 층 객체의 z 최소값을 FL에 맞춥니다.
- 마감 두께(+20 등)는 바닥 그룹 안에서 처리하고 가구는 마감면 위에 둡니다.
- 레벨 표가 없을 때는 이 모델의 값을 그대로 쓰지 말고 도면/사용자에게 확인합니다(이 값은 이 프로젝트 고유).

## 대지·지형·조경면
<!-- sion-guide id="terrain" order="8" after="levels" applies_to="terrain,site-container" tools="hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="def:그룹#45,def:그룹#32,def:그룹#33,def:그룹#38,def:그룹#39,def:그룹#11,mat:기존조경,mat:[Vegetation Grass]" -->

**[관측]**
- 기존 지형 `그룹#45`: 주 재질 `기존조경`(면 873개), 계단식 수평 레벨 0/3,000/5,500/8,000 + 3° 이상 경사면, 정의 크기 54.0 × 17.9 × 10.5 m, 월드 z -6,000부터.
- 계획 조경면: `[Vegetation Grass]` 재질. `그룹#32`(12.6~16.4° 경사), `그룹#33`(10.6~12.6°), `그룹#38`(인스턴스 재질, 월드 범위 41.2 × 50.1 m), `그룹#39`·`그룹#41`(0/1,000/2,000 계단식 단), `그룹#102`(19.6~49.2° 경사).
- 지형 그룹의 면 수는 수십~수백 개 수준(`그룹#45` 873, `그룹#39` 203, `그룹#41` 6)이다. **[추론]** 촘촘한 Sandbox 메시가 아니라 단(수평면)과 경사 평면을 손으로 이은 방식이다.
- `그룹#42`·`그룹#44`는 `@0818변경` 태그 색 재질(`<auto>2`)로 칠한 변경 표시면.
- 기존 지형은 `기존조경`, 계획 지형은 `[Vegetation Grass]`로 재질을 구분.

**[권장] 그리는 법**
1. CAD 등고선/레벨 점을 참조로 단(테라스)별 수평면을 만들고(`create_face` 또는 Ruby `add_face`), 단 사이를 경사면으로 잇습니다.
2. 지형은 부위별(기존/계획, 영역별) 그룹으로 나누고 이름에 레벨을 씁니다(`TER-기존-0~8000`).
3. 기존 지형과 계획 지형은 재질을 분리합니다(기존 `기존조경`, 계획 `[Vegetation Grass]`).
4. 변경 검토용 표시는 별도 그룹·별도 태그(`@0818변경`처럼 날짜 포함)로 두고, 확정 후 지웁니다.
5. 지형 면은 앞면(흰 면)이 위를 보게 합니다(`face.normal.z > 0`).

## 옹벽
<!-- sion-guide id="retaining-wall" order="9" after="terrain" applies_to="retaining-wall" tools="hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby,sketchup-mcp2.create_component" evidence="def:그룹#16,def:그룹#29,def:그룹#35,def:그룹#34,def:그룹#6,def:그룹#14,mat:Travertine Stretcher 3260 x 2660 mm (UMXUG9)" -->

**[관측]**
- 트래버틴 옹벽(정의 크기): `그룹#16`(수평 레벨 0/500/5,000/5,500, 10.6 × 41.9 × 5.5 m), `그룹#29`(0/4,500, 13.0 × 37.5 × 4.5 m), `그룹#35`(57.3 × 0.5 × 18.0 m), `그룹#14`(-5,500/0/4,500, 63.9 × 5.6 × 22.0 m, `기존조경` 면도 포함), `그룹#34`(수직면 270개, 5.6~7.5° 경사면 포함, 54.0 × 14.1 × 16.7 m).
- 재질 `Travertine Stretcher 3260 x 2660 mm (UMXUG9)` — 그룹 자체에 칠하거나(그룹#35, #34) 면에 칠함(그룹#16, #29).
- 벽돌 곡선 옹벽/화단 벽 `그룹#6`: 주 재질 `Even Drag Brick Staggered (6B2XZN)`(면 166개, 수직면 160개), 반경 800·1,000·1,800·2,000 mm 호, 레벨 -5,000/-50/0.
- `옹벽` 태그는 있으나 엔터티 0개(사용 안 함).

**[권장] 그리는 법**
1. 평면에서 옹벽 중심선을 따라 두께(설계값)를 가진 폐합 프로파일을 그리고 `push_pull`로 높이를 줍니다. 상단이 단차를 따라 바뀌면 구간별로 나눠 높이를 다르게 하거나 상단 면을 경사로 이동합니다.
2. 곡선부는 호 세그먼트 수를 일정하게(호 반경 800~2,000 mm 규모면 12~24분할) 맞춥니다.
3. 옹벽은 지형과 다른 그룹으로, 재질은 그룹에 칠해 일괄 변경이 쉽게 합니다.
4. 태그 `옹벽`(기존)을 붙입니다.
5. 옹벽 두께·높이는 이 모델에서 일반화하지 말고 설계 도면에서 받습니다(이 모델의 바운딩 크기는 경사·꺾임을 포함한 값이라 두께가 아님).

## 주차장 데크·경사로·주차구획·도로계획면
<!-- sion-guide id="parking" order="10" after="retaining-wall" applies_to="parking-deck,parking-stall,road-plan-surface,paving" tools="hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby" evidence="def:그룹#3,def:그룹#4,def:그룹#9,def:그룹#8,def:그룹#7,def:그룹#5,def:그룹#30,def:장애인주차,tag:도로계획" -->

**[관측]**
- 주차 데크·경사로 `그룹#3`(수평 바닥 131.6 m², 7.0~8.5°·11.1~11.6° 경사면), `그룹#4`(154.9 m², 7.2~8.7°·10.6~11.6°). 재질 `[Polished Concrete New]`.
- 주차면 `그룹#9`: 단일 수평면 341.9 m²(월드 z -2,500), 그 위에 구획 표시면 `그룹#8`(`[Quartz Light Grey]`, 도로계획 태그 선 12개).
- 도로계획면 `그룹#7`: `<auto>` 재질 평면 48.3 m², 도로계획 태그 선 21개. 외부 포장 `그룹#30`(68.0 m², z 0), `그룹#5`(3.3~7.0° 완경사).
- 장애인주차 2D 블록 `장애인주차`(3,350 × 5,000, @주차 태그)는 미사용 CAD 정의 안에만 있다.

**[추론]** 경사 7~8.5°(약 12~15%)는 주차 경사로 본체, 10.6~11.6°(약 19~20%)는 짧은 전이 구간으로 보입니다. 법규 적합 여부는 확인되지 않았습니다.

**[권장] 그리는 법**
1. 단별 주차면을 수평면으로 만들고(레벨별 그룹), 경사로는 시작·끝 레벨을 가진 4점 면으로 만든 뒤 두께를 줍니다.
2. 경사도는 설계값(%)으로 계산해 끝점 z를 정합니다: `dz = 길이 × 경사%/100`.
3. 주차구획선은 바닥면과 같은 높이의 별도 그룹(얇은 면 또는 선)으로 두고 태그 `@주차`를 붙입니다. 바닥면과 같은 평면에 겹치면 z-fighting이 생기므로 1~2 mm 띄우거나 바닥면을 분할합니다.
4. CAD 도로계획 선은 참조로만 쓰고 면을 만든 뒤 `<auto>` 재질은 실제 포장 재질로 바꿉니다.

## 외부계단·단차
<!-- sion-guide id="exterior-stair" order="11" after="parking" applies_to="exterior-stair,handrail,wall" tools="hueflow.execute_ruby,hueflow.create_face,hueflow.push_pull" evidence="def:그룹#18,def:그룹#19,def:그룹#23,def:그룹#21,def:그룹#24,def:그룹#31,obj:47944" -->

**[관측]**
- 외부계단 조립체 `그룹#18`(정의 크기 30.4 × 2.4 × 8.2 m, 대지와 같이 4.09° 회전): 계단 본체 2개(`그룹#19`·`그룹#23`, 인스턴스 이름 `Raise`), 핸드레일 2개(`그룹36#1`·`그룹53#1`, 이름 `Handrail`, 각각 `D=30 mm` 파이프 2개), 벽돌 측벽 4개.
- `그룹#19`: 수평 레벨 14개, 간격 166.7(=2,500/15), 1,333 높이에 참(3.28 m²). `그룹#23`: 수평 레벨 26개, 간격 166.7(=4,500/27). 재질 `[Polished Concrete New]`(인스턴스에 칠함).
- 측벽 `그룹#21`·`그룹#166`(10,600 × 300 × 3,700, 상단 17.7° 경사), `그룹#24`·`그룹#37`(13,000 × 300 × 5,700, 상단 29.8°). 재질 `Even Drag Brick Staggered (6B2XZN)`(인스턴스에 칠함).
- 계단식 단차 `그룹#31`: 수평 레벨 0/67/139·143/283·287/426/498/500(약 143 mm 단).

**[추론]** `Raise`, `Handrail`, `D=30 mm` 이름은 계단/난간 생성 플러그인이 붙인 이름으로 보입니다(어떤 플러그인인지는 덤프로 확인 불가).

**[권장] 그리는 법**
1. 총 높이 H와 단높이 목표값으로 단수 n = round(H / 목표 단높이)를 정하고 실제 단높이 = H/n으로 맞춥니다(이 모델: 2,500/15, 4,500/27).
2. 측면 프로파일(계단 단면)을 한 면으로 그린 뒤 계단 폭만큼 `push_pull` 합니다. 참은 프로파일 안에 넣습니다.
3. 계단 본체, 측벽, 난간을 각각 그룹으로 만들고 상위 `외부계단` 그룹으로 묶습니다(그룹#18 구조).
4. 측벽 상단은 계단 기울기를 따라 경사면으로 자릅니다.
5. 단높이·단너비는 법규·설계값을 따르고, 이 모델 값은 예시로만 씁니다.

## 난간·핸드레일·유리난간
<!-- sion-guide id="railing" order="12" after="exterior-stair,interior-stair" applies_to="handrail,glass-railing" tools="hueflow.follow_me,hueflow.execute_ruby,hueflow.create_circle" evidence="def:그룹#67,def:그룹#57,def:그룹#83,def:그룹#258,def:그룹#115,def:그룹#124,tag:XCLINE" -->

**[관측]**
- 강재 난간 `그룹#67`(정의 30 × 14,415 × 915, 인스턴스 Y축척 0.9029 → 월드 길이 13,015, 인스턴스 재질 `[Color M06]`): 반쪽 `그룹#64` ×2, 각각 `그룹#68`(난간동자 `그룹#57` 29개, 이름 `D=15 mm`, 15 × 15 × 889) + 핸드레일 `그룹#83`(`D=30 mm`).
- 계단 난간 `그룹#258`: 두께 44 mm 판 6개(`그룹356#1`~`그룹361#1`, 높이 1,300 위주) + `D=30 mm` 핸드레일 `그룹#259`(수평 레벨 885/915/4,535/4,565).
- 파이프 그룹 안에 `XCLINE` 태그 모서리(경로선)가 남아 있다(총 46개).
- 유리난간 `그룹#115`: 두께 0 유리면, 길이 14,960 × 높이 1,100, 월드 z 10,300. `그룹#124`: 6,400 × 9,400 × 1,200(z 10,200). 재질 `[Translucent Glass Gray]`(불투명도 0.4).

**[권장] 그리는 법**
1. 핸드레일은 경로선(계단 기울기 따라 오프셋한 선)에 원(지름 30)을 수직으로 두고 `follow_me`로 만듭니다. 경로선은 별도 태그(예: XCLINE처럼 보조선 태그)에 두거나 지웁니다.
2. 난간동자는 하나를 그룹/컴포넌트로 만들고 간격 배열합니다(이 모델: 반쪽 6.6 m마다 29개, 전체 58개). 반복 부재이므로 컴포넌트 권장.
3. 유리난간은 두께 없는 면 대신 두께(설계값) 있는 판으로 만들면 렌더·단면이 안정적입니다. 재질은 반투명 유리 하나로 통일합니다.
4. 난간 높이는 설계값(이 모델 915, 1,100, 1,200)을 따르고 바닥 마감면 기준으로 둡니다.

## 건물 매스 구성(동 단위 컨테이너)
<!-- sion-guide id="building-mass" order="13" after="exterior-stair" applies_to="building" tools="sketchup-mcp2.list_components,sketchup-mcp2.get_component_info,hueflow.create_group,hueflow.execute_ruby" evidence="obj:511546,def:그룹#201,def:그룹#161,def:그룹#217,def:그룹#105,def:그룹#202" -->

**[관측]**
- 본동 컨테이너 `그룹#201`(26.6 × 40.8 × 10.7 m, z 4,800부터): 하위 그룹 22개 + 컴포넌트 1개. 외피(`그룹#129`, `그룹#71`), 바닥·천장·지붕(`그룹#202`), 별동(`그룹#161`, `그룹#217`), 난간, 플랜터, 인물이 같은 층위에 섞여 있다.
- 1층 실내는 별도 최상위 `그룹#105`(→ `그룹#160`), 2층 핀은 별도 최상위 `새 블럭.dwg`, 기둥 `col`과 보 `그룹#89`도 최상위에 따로 있다.
- 별동: 상부 박스 `그룹#161`(9.0 × 9.0 × 3.63 m, z 9,150; 하위 `그룹#101` → 벽 `그룹#88`(`재질2`, RGB 244 + Non Slip Vinyl 텍스처) + 창 묶음 `그룹#76`(DimGray 프레임 + Blue Glass)), 하부 `그룹#217`(9.44 × 23.42 × 5.0 m, z 5,000; `그룹#234` → 판 `그룹#229` 등).

**[권장]**
- 동마다 최상위 그룹 하나(`B1-본동`, `B2-별동`)를 두고 그 안을 `층 > 부위`로 나눕니다. 이 모델처럼 기둥·보·실내가 동 컨테이너 밖에 흩어지면 동 단위 이동·숨김·물량 산출이 어렵습니다.
- 층 그룹은 FL을 z 최소값으로 맞춥니다(1층 +5,000, 2층 +10,200).
- 동 컨테이너를 만든 직후 `get_component_info`로 bbox를 읽어 대지 위 위치를 확인합니다.

## 바닥 슬래브·천장
<!-- sion-guide id="slab" order="14" after="building-mass" applies_to="floor-slab" tools="hueflow.create_box,hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby" evidence="def:그룹#203,def:그룹#133,def:그룹#213,def:그룹#204,def:그룹#231,def:그룹#229,def:그룹#40" -->

**[관측]**
- 2층 바닥/1층 천장 묶음 `그룹#202`: 접힌 천장 `그룹#203`(오크 마감, 수평 -800/0 + 29.7° 경사면, z 8,100)·`그룹#133`(Polished Concrete 15DBUL, -2,000/0 + 29.7°), 2층 바닥 `그룹#213`(수평면 618.6 m², 두께 470), `그룹#204`(두께 160, 2.8° 경사면, `지붕` 재질), 마감면 `그룹#231`(z 10,220, 두께 0).
- 별동 판 `그룹#229`(두께 30, 9.44 × 14.44 m, z 9,350). 1층 레벨 외부 바닥판 `그룹#40`(수평면 1,069.5 m², z 5,000).
- 장면 1·2 렌더에서 1층 천장은 경사면이 접힌 형태로 보인다.

**[권장] 그리는 법**
1. 슬래브는 외곽선 면 → `push_pull`(두께, 아래 방향)으로 만들고 상면을 FL에 맞춥니다.
2. 구조체와 마감(바닥 마감 20 mm 등)을 다른 그룹으로 나눕니다(이 모델: 구조 `그룹#213` + 마감면 `그룹#231`).
3. 접힌 천장은 단면 프로파일을 그려 길이 방향으로 `push_pull`하거나 꺾인 면을 이어 만듭니다. 천장은 바닥 그룹과 분리합니다.
4. 면 방향: 바닥 상면 앞면이 위로, 천장 하면 앞면이 아래로.

## 기둥·보
<!-- sion-guide id="column-beam" order="15" after="slab" applies_to="column,beam" tools="sketchup-mcp2.create_component,sketchup-mcp2.transform_component,hueflow.place_component,hueflow.execute_ruby" evidence="def:col,obj:2004749,obj:2004982,obj:2005214,obj:2005446,def:그룹#89,def:그룹#225" -->

**[관측]**
- 원형 기둥 컴포넌트 `col`: 반경 240(지름 480), 높이 4,200, 인스턴스 4개. 월드 최소점 x 70,273.7, y 22,505 / 28,405 / 38,905 / 44,005, z 5,000.
- 4개 중 2개(pid 2004749, 2004982)는 인스턴스 재질 `Polished Concrete None 3000 x 2152 mm (15DBUL)`, 2개는 재질 없음.
- 보: `그룹#89`(DimGray, 250 × 8,050 × 450, z 6,250, 최상위), `그룹#225`(`지붕` 재질, 300 × 8,050 × 450, z 6,250, 본동 안).

**[추론]** 기둥 상단 +9,200은 접힌 천장 그룹 `그룹#203`(z +8,100부터 높이 2,000) 범위 안이라 천장 속으로 들어가 보이도록 만든 것으로 보입니다. 2층 바닥 구조(`그룹#213`, z +9,750)까지는 닿지 않습니다.

**[권장] 그리는 법**
1. 기둥은 **컴포넌트 하나 + 인스턴스 배치**(그리드 교차점). `sketchup-mcp2.create_component(type="cylinder", dimensions=[480,480,4200], position=[x-240, y-240, 5000])` 후 정의 이름을 `COL-D480-H4200`으로 바꿉니다.
2. 재질은 정의 안 면에 칠해 모든 인스턴스를 통일합니다(이 모델처럼 인스턴스마다 다르게 칠하지 않음).
3. 보는 길이·폭·높이 박스로 만들고 하단 레벨을 명시합니다(z 6,250 등). 같은 단면 보가 반복되면 컴포넌트로.
4. 기둥 중심 좌표 = bbox 최소점 + 반지름(240)임을 기억합니다.

## 벽체
<!-- sion-guide id="wall" order="16" after="column-beam" applies_to="wall" tools="hueflow.create_box,hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby" evidence="def:그룹#247,def:그룹#88,def:그룹#109,def:그룹#227,def:그룹#157,def:그룹#21" -->

**[관측]**
- 실내 벽 `그룹#247`: 9,100 × 300 × 3,000(상단 2,970/3,000). 별동 벽 `그룹#88`: `재질2`(흰색) 8.94 m 정사각 박스, 높이 3,630, 개구부 레벨 다수.
- 조적 낮은 벽 `그룹#109`(1,425 × 22,500 × 600, 레벨 0/450/600) + 두겁 `그룹#227`(650 × 22,500 × 150, 45° 경사면).
- 계단실 벽 `그룹#157`(Travertine (ZUB1YX), 4,840 × 3,100 × 4,452). 외부계단 벽돌 측벽 `그룹#21` 등.
- 벽 그룹 이름·태그가 없어 덤프에서 벽 여부는 크기·재질로만 판단된다(@wall 태그는 CAD 정의에만 사용).

**[권장] 그리는 법**
1. 벽은 평면 외곽(두께 포함) 면 → `push_pull` 높이. 직선 벽은 `create_box(width=길이, depth=두께, height=높이, origin=[x,y,FL])`가 가장 빠릅니다.
2. 개구부는 벽 그룹 안에서 면을 나눠 `push_pull`로 뚫거나, 문·창 컴포넌트에 `cuts_opening`을 켭니다(이 모델 컴포넌트는 모두 cuts_opening=false).
3. 벽 그룹 이름에 층·위치·두께를 씁니다(`W-1F-300-01`), 태그 `@wall`.
4. 마감(트래버틴·벽돌)은 그룹 재질로 칠해 일괄 교체합니다.

## 커튼월·유리 외피·멀리언
<!-- sion-guide id="curtain-wall" order="17" after="wall" applies_to="curtain-wall" tools="hueflow.execute_ruby,sketchup-mcp2.create_component,hueflow.place_component" evidence="def:그룹#63,def:그룹#46,def:그룹#54,def:새 블럭.dwg,def:그룹#134,def:그룹#246,def:그룹#154,def:그룹#85,mat:[Translucent Glass Gray],mat:[Color M06]" -->

**[관측]**
- 1층 멀리언 프레임 `그룹#63`(`그룹#46` 안): `[Color M06]`(어두운 회색 86,86,86), 면 1,980개 중 수직면 1,944개, 22.0 × 23.95 × 5.05 m, 수평 레벨 0/5,050, `@win` 태그 선 1개.
- 2층 수직 핀/멀리언 `그룹#54`(`새 블럭.dwg` 안, z 10,200): `[Color M06]`, 수직면 1,728개, 21.6 × 21.8 × 4.56 m.
- 유리: `그룹#134`(1.9 × 22.2 × 5.0 m), `그룹#246`(두께 0, 13.5 × 5.0 m), 2층 `그룹#154`(`[Color_001]` + 유리, 수직면 101개). 재질 `[Translucent Glass Gray]`(불투명도 0.4).
- 단일 멀리언 부재 `그룹#85`: 450 × 30 × 4,000(`[Color M06]`).

**[추론]** 멀리언 프레임은 하나의 큰 그룹(면 수천 개)으로 만들어져 있어 개별 부재 수정이 어렵습니다. 2층 핀은 CAD 블록(`새 블럭.dwg`)에서 3D화한 것으로 보입니다.

**[권장] 그리는 법**
1. 멀리언 한 개(단면 × 높이)를 컴포넌트로 만들고 모듈 간격으로 배열합니다. 큰 덩어리 그룹 하나로 만들지 않습니다.
2. 유리는 프레임과 다른 그룹으로, 두께(예: 24 mm 복층 → 단순화하면 10~30 mm 판)를 주거나 단면 표현이 필요 없으면 면 하나로 둡니다.
3. 재질: 프레임 `[Color M06]` 계열 한 개, 유리 반투명 한 개로 통일합니다.
4. 커튼월 하단은 FL, 상단은 상부 슬래브/보 하단에 맞춥니다(1층 0~5,050).

## 문·창호·루버
<!-- sion-guide id="doors-windows" order="18" after="curtain-wall" applies_to="door,window-louver" tools="hueflow.execute_ruby,sketchup-mcp2.create_component,hueflow.place_component" evidence="def:그룹#257,def:그룹#253,def:그룹#254,def:그룹#77,def:그룹#82,def:그룹#96,def:그룹167#1,mat:Blue Glass,mat:DimGray" -->

**[관측]**
- 미서기 유리 패널 `그룹#257`·`그룹#248`: 3,255 × 70 × 2,910(레벨 0/30/2,880/2,910 → 프레임 30). 묶음 `그룹#249`.
- 문틀+유리문: `그룹#253`(문틀 2,450 × 180 × 2,970, `[Color M06]`) + 유리 문짝 `그룹#255`(1,150 × 2,770), `그룹#254`(1,200 × 60 × 2,770) + `그룹#256`(1,100 × 2,670).
- DimGray 프레임 + Blue Glass(불투명도 0.6) 창: 별동(`그룹#76` 안) `그룹#77`(5,600 × 200 × 600, z 11,300, 프레임 단 30/60/90), `그룹#82`(120 × 2,440 × 1,390, 프레임 60); 1층(`그룹#125` > `그룹#66` 안) `그룹#96`(7,050 × 200 × 900, z 6,800).
- 루버 `그룹167#1`(별동 `그룹#79` 안, 인스턴스 재질 DimGray): 살 24개(단면 940 × 87.7 × 100 형과 940 × 40 × 69.3 형 두 종류)가 100 mm 간격, 월드 범위 940 × 100 × 2,340(세로 배열).
- 모든 문·창이 그룹이며 이름이 없고 cuts_opening 컴포넌트가 없다. CAD 문 기호(`*U20`, @door)는 미사용 2D.

**[권장] 그리는 법**
1. 같은 규격 문·창은 **컴포넌트**(`DR-1150x2770-GL`, `WN-5600x600`)로 만들고 `cuts_opening`과 `snapto`(벽 수직면)를 켜서 벽에 붙입니다.
2. 프레임(30~60 mm 단)과 유리를 정의 안에서 다른 그룹으로 나눕니다.
3. 루버는 살 하나를 컴포넌트로 만들고 간격 배열합니다(이 모델: 100 mm 간격 24개, 높이 2,340).
4. 태그: 문 `@door`, 창 `@win`(CAD와 같은 이름).

## 지붕
<!-- sion-guide id="roof" order="19" after="doors-windows" applies_to="roof,beam" tools="hueflow.create_face,hueflow.push_pull,hueflow.execute_ruby,hueflow.create_roof_truss" evidence="def:그룹#207,def:그룹#219,def:그룹#223,def:그룹#214,def:그룹#156,mat:지붕" -->

**[관측]**
- 본동 지붕 `그룹#207`(z 13,363~15,450, 24.6 × 25.3 × 2.1 m): `그룹#219`(`지붕` 재질, 5.9° 경사면 40개, 수평 71.2 m²), `그룹#223`(5.9° + 처마 수직면 14개), `그룹#214`(5.9° 경사면 16개).
- 2층 상부 `그룹#156`(z 12,919, 수평 2,719/3,050/3,150 + 5.9~6.2° 경사).
- 지붕 재질은 한글 이름 `지붕`(153,153,153, 텍스처 없음)과 `재질3`.

**[추론]** 경사 5.9°(약 10.3%)의 완경사 지붕입니다. 지붕 재료(징크/강판 등)는 덤프로 알 수 없습니다.

**[권장] 그리는 법**
1. 지붕 외곽을 수평면으로 그린 뒤 용마루 선을 올리거나(`move` z) 단면을 그려 길이 방향 `push_pull`로 경사판을 만듭니다. 경사각은 설계값(°)으로 계산: `dz = 수평거리 × tan(각)`.
2. 지붕판·처마·보를 다른 그룹으로 나눕니다.
3. 목조 트러스가 필요하면 `hueflow.create_roof_truss`(king post/fink)를 쓰되, 이 모델에는 트러스가 없습니다.
4. 지붕 재질은 이름에 재료를 씁니다(`지붕-징크`, `지붕-골강판`) — 이 모델의 `지붕`처럼 재료를 알 수 없는 이름은 피합니다.

## 내부계단
<!-- sion-guide id="interior-stair" order="20" after="slab" applies_to="interior-stair" tools="hueflow.execute_ruby,hueflow.create_face,hueflow.push_pull" evidence="def:그룹#111,def:그룹#112,def:그룹#113,def:그룹#157,def:그룹#258" -->

**[관측]**
- 계단 묶음 `그룹#111`(5.65 × 8.99 × 5.35 m, 1층 → 2층): `그룹#112`(수평면 62개, 60 mm 디딤판 쌍이 약 153 mm 간격, 수직면 125개), `그룹#113`(수평면 31개, 153 mm 간격, 총 5,200), 계단실 벽 `그룹#157`.
- 32.5° 경사면 2개(계단 하부 경사판/옆판으로 추정).
- 계단 난간은 `그룹#258`(44 mm 패널 + D=30 핸드레일).

**[추론]** 층고 5,200을 34단 × 152.9 mm로 나눈 계단입니다. 디딤판 두께 60 mm는 `그룹#112`의 수평면 쌍 간격에서 나온 값입니다.

**[권장] 그리는 법**
1. 층고 H(FL 차)와 목표 단높이로 단수를 정하고 실제 단높이 = H/n.
2. 디딤판(두께 t) 하나를 그룹/컴포넌트로 만들고 단높이·단너비 간격으로 배열하거나, 측면 프로파일을 `push_pull`합니다.
3. 계단 본체·옆판·난간·계단실 벽을 분리합니다.
4. 상부 슬래브에 계단 개구부를 뚫었는지 단면으로 확인합니다.

## 카운터·붙박이 가구
<!-- sion-guide id="millwork" order="21" after="wall" applies_to="counter-millwork" tools="hueflow.create_box,hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="def:그룹#61,def:그룹#164,def:그룹#155,def:그룹#158,def:그룹#165,def:그룹#163,def:그룹#226" -->

**[관측]**
- 메인 카운터 `그룹#61`: 5,020 × 3,400 × 1,200, 주 재질 Oak (UPFJJT)·[Color M07]·석재(Limestone, Flagstone 등), 반경 350 곡면, 위에 유리 진열장 `그룹#164`(1,955 × 763 × 598, `[Translucent Glass Gray]1`).
- 백카운터 `그룹#155`: 10,025 × 3,400 × 1,100, 상판 `그룹#158`(두께 40, 면 재질 Limestone (X9W4RQ) + 인스턴스 재질 `바닥1`) + 수납 `그룹#165`(높이 960, Victorian Glazed 타일 + Oak (UPFJJT)).
- 붙박이 벤치 `그룹#163`: Limestone, 650 × 16,793 × 550(레벨 0/470/550). 2층 바/좌석대 `그룹#226`(2,150 × 17,126 × 650, 스툴 `c3#2` ×8 포함).

**[권장] 그리는 법**
1. 몸체(박스) → 상판(두께 30~40) → 전면 마감 순으로 그룹을 나눕니다.
2. 곡면 전면은 평면 외곽에 호(반경 설계값)를 넣어 `push_pull`.
3. 붙박이 가구는 해당 층 그룹 안에 두고 FL 위에 놓습니다. 반복되지 않으면 그룹, 반복되면 컴포넌트.

## 가구 배치
<!-- sion-guide id="furniture" order="22" after="millwork" applies_to="furniture" tools="hueflow.place_component,sketchup-mcp2.transform_component,sketchup-mcp2.find_components,hueflow.execute_ruby" evidence="def:C1,def:T,def:T2,def:SO,def:ch5,def:ch6,def:c3,def:c3#2,def:그룹#160,def:그룹#232" -->

**[관측]**
- 1층 세트 `그룹#160`: 의자 `C1`(450 × 460 × 741) ×47(회전 0°/180°, 인스턴스 재질 Oak Veneer), 테이블 `T`(800 × 800 × 700) ×8, `T2`(2,400 × 900 × 700, 상판 40) ×5, `SO`(1,500 × 650 × 560) ×8.
- 2층(`그룹#205` 안): 스툴 `c3`(510 × 480 × 700) ×6, 벤치 `ch5`(1,590 × 630 × 745) ×3 + `그룹#232` 안 8개, 가죽 좌석 `ch6`(837 × 1,874 × 577) ×5. `그룹#226` 안 스툴 `c3#2`(600 높이) ×8.
- 가구 컴포넌트는 모두 축척 1.0, 회전만 사용. 미사용 가구 정의 `T#1`, `t3`, `c3#1`, `Componente`(3D Warehouse).
- `c3`/`c3#2`의 좌판은 면 4,710개(고밀도 메시).

**[권장] 그리는 법**
1. 가구는 반드시 컴포넌트, 이름에 규격(`CH-450x460x741`). 배치는 `place_component(name, origin)` 또는 Ruby `entities.add_instance(defn, tr)`.
2. 축척하지 말고 회전·이동만 합니다(이 모델 방식). 다른 크기는 새 정의로.
3. 가구 세트는 층·실 단위 그룹으로 묶습니다(`그룹#160`처럼). 배치 간격은 테이블 기준으로 계산합니다.
4. 고밀도 메시 가구(면 수천 개)는 반복 수가 많으면 모델이 무거워지므로 저폴리 대체를 고려합니다.

## 플랜터·수목
<!-- sion-guide id="landscape" order="23" after="terrain,building-mass" applies_to="planter,tree" tools="hueflow.place_component,hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="def:그룹#74,def:Component#28,def:그룹#65,def:그룹#62,def:그룹#72,def:그룹#73,tag:Trees 3D,mat:Vegetation_Bark_Birch" -->

**[관측]**
- 수목 = 수관 그룹 `그룹#74`(면 825, 모서리 35,512, 재질1·birch-yellow texture2·[Color_D09], 수관 엔터티 태그 `Trees 3D`) + 줄기 컴포넌트 `Component#28`(Vegetation_Bark_Birch, 인스턴스 태그 `Trees 3D`, 정의 높이 8,296.8, 인스턴스 축척 0.754 × 0.754 × 0.7316).
- 수목 그룹은 비균일 축척(11개 0.4271/0.4271/0.457, 3개 0.3203/0.3203/0.27~0.37)으로 배치, 회전은 그루마다 다름(-133°~156°).
- 수목 16그루: `그룹#65`(z 5,000) 안 13그루(`그룹#74` ×11 + 같은 형상 사본 그룹 `그룹#53`·`그룹#56`), 플랜터 `그룹#62`·`그룹#72`·`그룹#73`(상면 3.24 m², 높이 450) 안 3그루(z 5,225).
- 수목 정의 하나가 모서리 35,512개로 무겁다(`그룹#74`·`그룹#53`·`그룹#56` 정의 합계 약 10.6만 개, 모델 전체 정의 모서리 427,343개의 약 25%).

**[권장] 그리는 법**
1. 수목은 **컴포넌트 하나**(수관+줄기 포함)로 만들고 축척은 균일하게(높이만 다르면 균일 축척으로 조정) 배치합니다. 회전을 섞어 반복감을 줄입니다.
2. 태그 `Trees 3D`(기존)에 두어 무거운 수목을 한 번에 숨길 수 있게 합니다. 이 모델은 수관 그룹 인스턴스가 Layer0이라 태그만으로 숨겨지지 않습니다.
3. 플랜터는 박스(높이 450 등) 그룹으로 만들고 수목 인스턴스를 플랜터 상면에 놓습니다.
4. 저폴리/2D 수목(face-me) 대안을 검토합니다(작업용 장면에서 성능).

## 인물(스케일 피겨)
<!-- sion-guide id="people" order="24" after="furniture" applies_to="person" tools="hueflow.place_component,sketchup-mcp2.transform_component,sketchup-mcp2.get_component_info" evidence="def:Component18,def:그룹#110,def:그룹#116,def:그룹#130,def:그룹#139,def:Niraj" -->

**[관측]**
- 인물 그룹 4개(`그룹#110`, `그룹#116`, `그룹#130`, `그룹#139`), 각각 `Humano4_*` 등 구성 요소 2개(축척 0.0394 = 1/25.4), 그룹 높이 약 1.30~1.37 m.
- 서 있는 인물 `Component18`(인스턴스 이름 `CWom0105-HD2-O01P02-S005`), 높이 1,752, 축척 0.3937(= 1/2.54). 텍스처 파일명이 중국어(`集简空间…`)인 외부 라이브러리 모델.
- SketchUp 기본 인물 `Niraj`(always_face_camera=true)는 미사용.

**[추론]** 축척 1/25.4, 1/2.54는 inch·cm 단위로 만들어진 외부 모델을 mm 모델에 맞추려고 줄인 흔적입니다. 1.3 m 내외 인물은 앉은 자세로 보입니다.

**[권장]**
- 외부 인물 모델은 가져올 때 단위를 맞춰 **축척 1.0** 정의로 만듭니다(정의를 열어 크기 조정 후 축척 초기화). 축척된 인스턴스는 치수 조회 시 오해를 부릅니다.
- 인물은 컴포넌트, 태그 `@사람`, 바닥 마감면 위에 둡니다. 서 있는 인물 키 1,600~1,800 범위를 확인합니다.

## 주석·치수·표식
<!-- sion-guide id="annotation" order="25" after="cad-import" applies_to="annotation,marker,parking-stall" tools="hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="def:gfhfhgh,def:dfdsfdsfsdf,def:fghfghfh,def:그룹#12,tag:DIM,tag:@DIM" -->

**[관측]**
- SketchUp 텍스트·치수 엔터티 0개, 안내선(construction line) 0개. 구성점 108개는 모두 미사용 정의 안(`그룹#107` 96개, `ID_C_G4_T` 12개).
- 2D 주석 블록 `gfhfhgh` ×24, `dfdsfdsfsdf` ×18, `fghfghfh` ×28(각 225 × 225, 인스턴스 태그 모두 DIM)은 미사용 CAD 정의(`인테리어`, `새 블럭.dwg#1`) 안에만 있다.
- 빨간 표식 판 `그룹#12`(250 × 250, `[Color A06]`) 최상위 2개(z 9,819, z 12,364) — 용도 미상.

**[권장]**
- 3D 모델 안의 주석은 SketchUp 치수/텍스트로 별도 태그(`@DIM`, `@text`)에 두고 장면별로 켜고 끕니다.
- 의미 없는 이름의 CAD 블록(`gfhfhgh`)은 가져온 뒤 이름을 바꾸거나 정리합니다.
- 검토용 표식은 이름(예: `MARK-검토-0914`)과 태그를 붙여 나중에 찾아 지울 수 있게 합니다.

## 재질 규칙
<!-- sion-guide id="materials" order="26" after="group-component" applies_to="retaining-wall,terrain,curtain-wall,floor-slab,roof,furniture,wall,parking-deck" tools="hueflow.list_materials,sketchup-mcp2.set_material,hueflow.execute_ruby" evidence="mat:[Translucent Glass Gray],mat:[Color M06],mat:지붕,mat:기존조경,mat:<auto>,mat:Travertine Stretcher 3260 x 2660 mm (UMXUG9),mat:[Polished Concrete New]" -->

**[관측]**
- 재질 130개: 텍스처 있음 70, 사용 0회 32, CAD 색 자동 재질 `<auto>…` 28, SketchUp 기본 라이브러리 `[…]` 16, 한글 이름 11(`지붕`, `바닥1`, `바닥2`, `짙은바닥`, `기존조경`, `책상상판`, `재질`, `재질1`, `재질2`, `재질3`, `재질70`).
- 반투명: `[Translucent Glass Gray]` 0.4, `[Translucent Glass Gray]1` 0.5, `Blue Glass` 0.6, `재질` 0.8, `Humano4_0013` 0.03.
- 주요 대응: 옹벽 Travertine Stretcher, 외부계단·주차 `[Polished Concrete New]`, 벽돌 `Even Drag Brick Staggered (6B2XZN)`/(2OE7HP), 프레임 `[Color M06]`, 창틀 DimGray, 지형 `기존조경`/`[Vegetation Grass]`, 지붕 `지붕`, 바닥 오크 `Barham & Sons Benchmark Oak…`.
- 같은 텍스처를 쓰는 중복 재질이 있다(`[Vegetation Grass]`·`[Vegetation Grass]1`·`기존조경`이 모두 Vegetation_Grass1.jpg).
- 그룹/인스턴스에 칠한 재질과 면에 칠한 재질이 섞여 있다(예: `col` 4개 중 2개만 인스턴스 재질).

**[권장]**
- 재질 이름은 `부위-재료-색`(예: `옹벽-트래버틴`, `지붕-골강판-회색`)으로, `재질1` 같은 이름은 쓰지 않습니다.
- 재질은 **정의 안 면**에 칠하고, 인스턴스 재질은 같은 정의의 변형이 필요할 때만 씁니다.
- 유리는 반투명 재질 하나(불투명도 0.4 내외)로 통일합니다.
- `sketchup-mcp2.set_material`은 색 이름/HEX만 받으므로, 텍스처 재질은 Ruby(`model.materials.add`, `material.texture = 경로`)로 만듭니다.
- 사용 0회 재질 정리는 사람 승인 후에만 합니다.

## 장면·스타일·단면
<!-- sion-guide id="scenes" order="27" after="roof" applies_to="building,furniture,curtain-wall" tools="sketchup-mcp2.export_scene,hueflow.execute_ruby" evidence="scene:1,scene:2,scene:3,section:1" -->

**[관측]**
- 장면 3개(장면 1·2·3), 모두 원근 FOV 35°, 카메라·숨긴 태그·스타일·단면·축·그림자 저장. 선택된 장면은 `장면 2`.
- 스타일 3개(`[Architectural Design Style]`, `…1`, `…2`), 장면 1은 `…1`, 장면 2·3은 `…2`.
- 카메라 눈높이 z 6,679.3 / 6,452.2(1층 FL +5,000 기준 약 1.45~1.68 m), 장면 3은 z 11,401.1(2층 FL +10,200 기준 약 1.2 m). 장면 1·2는 수평 시선(눈과 목표점 z 동일), 장면 3은 약간 내려다보는 시선.
- 단면 `단면 1`: 최상위, 활성, 법선 +Y, y ≈ 23,411.7 mm(평면식 d는 inch 값 -921.72).

**[권장]**
- 실내 투시도 장면은 FL + 1,500 안팎 눈높이, FOV 35°, 수평 시선(2점 투시)으로 저장합니다.
- 장면마다 저장 항목(카메라, 태그 표시, 스타일, 단면)을 명시하고, 스타일은 장면별로 필요한 만큼만 만듭니다(같은 설명의 스타일 3개는 정리 대상).
- 단면은 이름에 위치를 씁니다(`단면-Y23400`).
- 이미지 출력은 `sketchup-mcp2.export_scene(format="png")`(현재 뷰) 또는 Ruby `view.write_image`. 다른 시점을 찍을 때는 카메라를 저장했다가 반드시 복원합니다.

## 모델 정리(미사용 정의·임시 태그)
<!-- sion-guide id="cleanup" order="28" after="scenes" applies_to="unused-definition,imported-3d,cad-reference" tools="hueflow.list_components,sketchup-mcp2.find_components,hueflow.execute_ruby" evidence="def:그룹#107,def:3DGeom~1_Defintion,def:Niraj,def:Componente,tag:LIBFREDO6_TEMP_LAYER" -->

**[관측]**
- 루트에서 도달하지 않는 정의 59개(인스턴스 0개 38개 + 미사용 정의 안에만 있는 21개): CAD 2D(`그룹#107`, `인테리어`, `우리필지배경`, `새 블럭.dwg#1·#2`, `f2.dwg`, `ST.dwg`, `ZIUM_sheet_architect` …), 외부 3D(`3DGeom~1…20_Defintion` 20개, 한 축이 정확히 25,400 = 1,000 in), 기본 인물 `Niraj`, 3D Warehouse 가구 `Componente`, 가구 사본 `T#1`, `t3`, `c3#1`.
- 재질 32개 사용 0회, 태그 4개 엔터티 0개.

**[권장]**
- 에이전트는 purge·삭제를 **하지 않습니다**. 정리 후보 목록(이 그래프의 `unused-definition` 분류)을 사용자에게 보고하고 승인을 받습니다.
- 승인 후 순서: 모델 사본 저장(사용자) → 미사용 정의 purge → 미사용 재질 → 빈 태그. 플러그인 임시 태그는 남깁니다.
- 정리 전후 정의/재질/태그 수를 비교해 기록합니다.

## QA 체크리스트
<!-- sion-guide id="qa" order="29" kind="checklist" after="cleanup" applies_to="building,floor-slab,wall,curtain-wall,roof,furniture,tree,terrain,retaining-wall,column" tools="sketchup-mcp2.get_model_info,sketchup-mcp2.list_components,sketchup-mcp2.get_component_info,hueflow.execute_ruby,sketchup-mcp2.export_scene" evidence="model:" -->

각 항목은 덤프(읽기 전용 Ruby)로 자동 확인할 수 있습니다.
1. 단위 mm, 정밀도·스냅 설정(UnitsOptions)이 프로젝트 기준과 같다.
2. 최상위 엔터티가 동/대지/조경 등 의미 있는 컨테이너뿐이고 느슨한 면·선이 없다(이 모델: 느슨한 엔터티는 단면 평면 1개뿐).
3. 모든 그룹·컴포넌트에 의미 있는 이름이 있다(`그룹#N` 기본 이름 0개 목표 — 이 모델 228개).
4. 형상은 Layer0, 인스턴스에만 태그. 빈 태그·CAD 잔여 태그가 장면에 영향을 주지 않는다.
5. 층 객체의 z 최소값이 FL과 일치(1층 5,000, 2층 10,200 등), 바닥 위 가구·인물이 마감면 위에 있다.
6. 반복 객체는 컴포넌트이고 축척 1.0(인물 1/25.4·1/2.54, 수목 비균일 축척 같은 예외를 목록화).
7. 면 방향: 지형·바닥 상면 앞면이 위. 유리 반투명 재질 통일.
8. 무거운 객체(수목 모서리 수만 개, 고밀도 의자) 목록과 숨김 태그 준비.
9. 장면별 카메라·스타일·단면 저장 상태 확인, 렌더 이미지로 육안 확인.
10. 미사용 정의·재질 수 보고(삭제는 승인 후).
11. 저장되지 않은 변경 여부(`model.modified?`)를 사용자에게 알리고, 에이전트는 저장하지 않는다.

## MCP 도구로 실행하는 방법(에이전트 절차)
<!-- sion-guide id="mcp-execution" order="30" kind="mcp" after="qa" applies_to="wall,floor-slab,column,furniture,tree,building,terrain,curtain-wall" tools="sketchup-mcp2.get_model_info,sketchup-mcp2.list_components,sketchup-mcp2.find_components,sketchup-mcp2.get_component_info,sketchup-mcp2.create_component,sketchup-mcp2.transform_component,sketchup-mcp2.set_material,sketchup-mcp2.create_layer,sketchup-mcp2.export_scene,sketchup-mcp2.eval_ruby,sketchup-mcp2.undo,hueflow.execute_ruby,hueflow.create_box,hueflow.create_group,hueflow.place_component,hueflow.list_materials" evidence="model:" -->

**서버**: `sketchup-mcp2`(도구 22개, 모든 좌표·치수 mm로 명시, 브리지 호출 시 기동에 약 60초)와 `Hueflow`(`claude:hueflow-sketchup`, 도구 21개, 기동 빠름).
브리지: `<USER_HOME>\grokbot-mcp-bridge\mcp-call.mjs`(`tools`/`call`, 인자는 `--args-file`로).

**1. 읽기(항상 먼저, 모델 변경 없음)**
- `get_model_info`(두 서버 모두) → 단위·범위·수량.
- `sketchup-mcp2.find_components(name, layer, type, max_depth)` / `list_components(recursive=true)` → 대상 bbox(mm, 월드).
- 대량 조회는 `hueflow.execute_ruby`로 읽기 전용 Ruby를 실행해 JSON 파일로 씁니다(`scripts/sketchup/dump_model.rb`). 호출마다 서버가 새로 뜨므로 한 번에 모아서 실행합니다.

**2. 만들기(사용자가 요청한 경우에만)**
- 단일 박스/원기둥: `sketchup-mcp2.create_component(type, position=bbox 최소점, dimensions mm, name)` → 응답 `bbox_mm` 확인.
- 이동/회전: `sketchup-mcp2.transform_component(id, position=절대 bbox 최소점, rotation, scale)`.
- 색: `sketchup-mcp2.set_material(id, "#rrggbb")`. 태그: `create_layer(name)`.
- 복합 형상은 `hueflow.execute_ruby`에서 한 작업 단위로:
```ruby
m = Sketchup.active_model
m.start_operation('W-1F-300-01 생성', true)
g = m.active_entities.add_group
g.name = 'W-1F-300-01'
pts = [[0,0],[9100,0],[9100,300],[0,300]].map { |x, y| Geom::Point3d.new(x.mm, y.mm, 5000.mm) }
f = g.entities.add_face(pts)
f.reverse! if f.normal.z < 0
f.pushpull(3000.mm)
g.layer = m.layers['@wall'] || m.layers.add('@wall')
m.commit_operation
g.bounds.min.to_a.map(&:to_mm).inspect + ' ' + [g.bounds.width, g.bounds.height, g.bounds.depth].map(&:to_mm).inspect
```
- 컴포넌트 배치: `hueflow.place_component(name, origin)` — origin 단위는 Ruby에서 `.mm`로 확인하고, 불확실하면 `execute_ruby`에서 `Geom::Transformation.new(Geom::Point3d.new(x.mm, y.mm, z.mm))`로 직접 배치합니다.

**단위 주의 [관측]**: Hueflow `create_face` 설명은 좌표가 "SketchUp 기본 단위(모델이 metric이 아니면 inch)"라고 적고, `create_box`·`place_component` 등은 단위를 밝히지 않으며, `create_roof_truss`는 span을 **feet**, spacing·overhang·origin을 **inch**로 받습니다. 치수가 중요한 형상은 `execute_ruby`에서 `.mm`로 명시하거나 `sketchup-mcp2` 도구(mm 고정)를 씁니다. `sketchup-mcp2.create_component`의 원기둥 `dimensions`는 [0]=지름, [2]=높이이고 각 값은 0.1 이상이어야 합니다.

**3. 확인**: 작업 직후 bbox·레벨을 다시 읽고 지침의 수치와 비교. 이미지는 `export_scene(format="png")`(현재 뷰) — `get_viewport_screenshot`은 SketchUp 2026 필요.

**4. 금지**: 사용자 승인 없는 `model.save`, `export_scene(format="skp")`(기본값이 skp이므로 png/jpg를 명시), purge, 삭제(`delete_component`), `undo` 남용. 저장되지 않은 변경이 있는 모델에서는 읽기만 하고 결과를 보고합니다. 설정 파일의 API 키를 출력하지 않습니다.

## 에이전트 판단 규칙(GraphRAG 조회 → 판단 → 실행)
<!-- sion-guide id="agent-judgement" order="31" kind="agent" after="mcp-execution" applies_to="site-container,building,terrain,retaining-wall,parking-deck,exterior-stair,handrail,glass-railing,floor-slab,wall,curtain-wall,door,window-louver,column,beam,roof,interior-stair,counter-millwork,furniture,planter,tree,person,annotation,cad-reference,unused-definition" tools="hueflow.execute_ruby,sketchup-mcp2.find_components" evidence="model:" -->

1. **요청 해석**: "옹벽 그려줘", "2층 의자 배치" 같은 요청에서 클래스(`retaining-wall`, `furniture`)와 층(레벨)을 정합니다.
2. **조회**: GraphRAG `mix` 질의로 클래스 노드 → `applies_to_class` 지침 청크 → `classified_as` 예시 정의(크기·재질·레벨·태그)를 가져옵니다. 예: `{"question": "SketchUp 옹벽 그리는 방법과 이 모델의 옹벽 예시", "mode": "mix"}`.
3. **사실 확인**: 예시 수치는 정의/인스턴스 노드의 `properties`(bounds_size_mm, first_world_bounds_mm, geometry_probe)에서 읽습니다. 분류 엣지(추론, unverified)만으로 치수를 정하지 않습니다.
4. **누락 판단**: 설계값(두께, 높이, 경사, 단높이)이 요청·도면에 없으면 이 모델 값을 "예시"로 제안하고 사용자 확인을 받습니다.
5. **실행 계획**: 지침의 그리는 법 단계를 MCP 호출 목록으로 바꿉니다(읽기 → 만들기 1작업 단위 → 확인). 한 호출 = 한 undo 단계.
6. **현재 모델 확인**: 열린 모델이 다를 수 있으므로 `get_model_info`로 파일·단위를 먼저 확인하고, 기존 객체와 겹치는지 `find_components`로 봅니다.
7. **보고**: 만든 객체의 id·이름·bbox(mm)·태그·재질을 보고하고, 추론에 기댄 결정은 추론이라고 밝힙니다.
