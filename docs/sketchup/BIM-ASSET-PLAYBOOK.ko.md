# BIM 자산 모델링 플레이북 (기준 모델: 0914_담당미팅)

이 문서는 `0914_담당미팅.skp`(학장동 경사지 파빌리온)를 분석해서, **다른 건물도 같은 방식으로 만들 수 있도록** 구성 방법·그룹 계층·레벨·클래스별 작성 순서·매핑 규칙을 정리한 것입니다. 수치는 읽기 전용 분석(run2 덤프, run3 구조·프로그램·외피·품질 분석)에서 나왔고, 분류는 모두 **추정·미검증**(/review 승인 전)입니다.

함께 보기: [zium-sketchup 가이드](https://github.com/khs0927/zium-sketchup/blob/main/docs/ZIUM_SKETCHUP_GUIDE.md), `MODELING-GUIDELINES.ko.md`, `GROUPING-WORKFLOW.ko.md`, `0914-REGROUP-PLAN.ko.md`, 생성기 `scripts/sketchup/generators/`.

## 1. 이 건물은 어떻게 구성돼 있나

- 대지 약 100.7 × 64.1 m(≈6,456㎡), Z −11.66 ~ +15.45 m의 경사지. 옹벽 6개로 단을 만들고 외부계단·3단 주차데크(−2.5 / +0.5 / +4.0 m)로 연결.
- 본관 파빌리온(그룹#129, ≈416㎡): 1층 커튼월(높이 ≈5.0 m) + 2층 커튼월(≈4.6 m) + 깊은 처마 평지붕(경사 ≈5.9°, 처마 W 1.8 / S 1.4 / E 0.7 / N 0 m).
- 별동 화이트박스(그룹#217 + 상부 #161, ≈221㎡). 그룹#105는 별동이 아니라 **본관 1층 카페 가구·커튼월 묶음**.
- 구조: Ø480 기둥 4개 1열(X≈70.3 m, 간격 5.9 / 10.5 / 5.1 m, +5.0 m에서 높이 4.2 m), 보 2개(8,050 × 춤 450), 2층 슬래브 ≈25.7 × 27.3 m, 두께 ≈160.
- 품질: 표시 면 ≈26만, 그중 의자 블럭(4,710면 × 36) ≈17만. 정의 297(미사용 59), 완전 중복 17묶음, 태그 49(43개 비어 있음), 최상위 전부 Layer0·무명.

## 2. 그룹 계층 패턴 (SITE / BLDG / STR / INT)

원본은 그룹#201 하나에 6단계로 몰려 있습니다. 새 건물은 처음부터 아래 4단계 이하로 만듭니다.

```
SITE                      대지(AREA 면), 지형, 도로, 포장
├─ SITE-RW-*              옹벽            (retaining-wall)
├─ SITE-ST-*              외부계단         (stair)
├─ SITE-PK-T1..Tn         주차데크 단      (parking-deck)
└─ SITE-LAND              나무·사람 블럭   (asset-block)
BLDG-<동이름>             예: BLDG-본관, BLDG-별동
├─ BLDG-1F / 2F / RF      층 컨테이너 (바닥 높이로 소속 결정)
│  ├─ STR-COL-<레벨>      기둥 그리드      (column)
│  ├─ STR-SLAB-<레벨>     슬래브           (slab)
│  ├─ STR-BEAM-*          보
│  ├─ ENV-CW-<레벨>       커튼월 + 멀리언   (curtain-wall / mullion)
│  ├─ ENV-GR-*            유리난간         (glass-railing)
│  ├─ ENV-ROOF            처마 지붕        (roof)
│  └─ INT-<실>            가구·카운터 블럭  (asset-block)
REF-CAD-*                 가져온 dwg (출력 제외 태그)
```

규칙: 최상위에 무명·Layer0 객체 금지. 반복되는 것은 **그룹이 아니라 컴포넌트**로(의자 36개 = 정의 1개). 나무·사람·가구는 내부를 그래프에 넣지 않고 **블럭 1개 = 자산 1개**로 기억합니다.

## 3. 레벨

| 이름 | 0914 값(mm) | 비고 |
|---|---|---|
| `GL ±0` | 0 | 대지 기준 |
| `1 FL +5000` | 5000 | 본관·별동 1층 |
| `2 FL +10200` | 10200 | 2층 바닥 |
| `RF TOS +14600` | 14600 | 지붕 상단 |

다른 건물은 이름 형식(`<층> FL +<mm>`)만 유지하고 값은 바꿉니다. 레벨면은 `ZIUM-LEVEL` 태그(비출력).

## 4. 클래스별 만드는 법 (레시피)

각 레시피는 `scripts/sketchup/generators/recipes.json`의 생성기와 1:1입니다. 모든 생성기는 한 번의 operation이라 Ctrl+Z 한 번으로 되돌아갑니다.

| 클래스 | 생성기 | 0914 예시 파라미터 | 순서 |
|---|---|---|---|
| column | `column_grid` | `xs:[70273.7], y0:22505, ys_spacing:[5900,10500,5100], base:5000, height:4200, dia:480` | 그리드 축 → 원 단면 → 높이 |
| slab | `slab` | `outline: 25700×27300, top:10200, thk:160` | 외곽선 → 상단 레벨에서 아래로 두께 |
| curtain-wall | `curtain_wall` | `length 22500, base:5000, height:5000, module_w:1500, mullion:[50,150]` | 유리판 → 수직 멀리언 → 상·하 트랜섬 |
| glass-railing | `glass_railing` | `base:10200, height:1200` | 경로 → 유리판 → 캡. **1200 미만이면 경고**(0914 #115=1.10 m, #67=0.92 m 확인 필요) |
| stair | `stair` | 외부 `width:2400, riser_max:170`(실측 ≈167), 실내 `width:3200`(≈153) | 층고/단높이로 단수 → 단 |
| retaining-wall | `retaining_wall` | 단차형 `height:4500~5500, thk:300` | 경로 → 벽 → 기초 |
| roof | `roof` | `base:14600, slope_deg:5.9, overhang:{w:1800,s:1400,e:700,n:0}` | 외곽 + 처마 → 두께 → 경사 |
| parking-deck | `parking_deck` | `base: -2500 / 500 / 4000, stalls ≈ 6~8 per tier` | 단 슬래브 → 주차면 선. 경사로 기울기 확인 |
| asset-block | `place_block` | `asset_id:'0914:furniture:c3'` | 라이브러리에서 정의 로드 → 배치 → 태그 |
| window | `window` | `width:2500, height:1450, sill:1070, operation:'sliding', facing:'E'` | 개구부 → 틀 4변·멀리언 → 유리 그룹 → WIN 태그 |
| fire-entry-window | `fire_entry_window` | `width:2000, height:2400, sill:0, glass:'tempered-5', facing:'S'` | 틀·유리 → 붉은 역삼각형·타격지점 → 기준 경고(참고용) |
| louver | `louver` | `width:940, height:2340, blade_w:100, pitch:100, direction:'horizontal'` | 살 1개 → 간격 배열 → LOUVER 태그 |

사용 예:

```ruby
Dir['C:/CODE/Ontology-platform/scripts/sketchup/generators/*.rb'].each { |f| load f }
SionBim.column_grid(xs: [70273.7], y0: 22505, ys_spacing: [5900, 10500, 5100], base: 5000, height: 4200, dia: 480)
SionBim.roof(x0: 0, y0: 0, w: 22000, d: 21800, base: 14600, overhang: { w: 1800, s: 1400, e: 700 }, slope_deg: 5.9)
```

## 5. 매핑 규칙 (SketchUp → IFC / 재질 / 태그)

| class | 지음 태그 | IFC | 기본 재질 | 0914 원본 재질 예 |
|---|---|---|---|---|
| column | COL | IfcColumn | 노출콘크리트 | — |
| slab | COL | IfcSlab | 노출콘크리트 | — |
| beam | COL | IfcBeam | 노출콘크리트 | — |
| curtain-wall | WIN | IfcCurtainWall | ZIUM-GLASS | Translucent Glass Gray, Blue Glass |
| mullion | WIN | IfcMember | ZIUM-MULLION | DimGray |
| glass-railing | STL | IfcRailing | ZIUM-GLASS | — |
| stair | STAIR | IfcStair | 노출콘크리트 | — |
| retaining-wall | COL | IfcWall | 노출콘크리트 | — |
| roof | COL | IfcRoof | ZIUM-ROOF | — |
| parking-deck | ETC | IfcSlab | 아스팔트 | — |
| asset-block(가구) | FUR | IfcFurnishingElement | 원본 유지 | — |
| asset-block(나무·사람·차) | ETC | IfcFurnishingElement / IfcGeographicElement | 원본 유지 | — |
| CAD 참조 | (출력 제외) | — | — | Defpoints, XCLINE, DIM 등 |

모든 객체에 속성 사전 **`sion_bim`**을 붙입니다: `asset_id`, `class`, `ifc`, `tag`, `level`, `schema = sion-bim/1`, 그리고 클래스별 치수(`height_mm`, `thk_mm`, `module_mm` …). 지음 호환을 위해 `zium/kind`도 같이 씁니다. 온톨로지 수집기는 이 속성을 그대로 노드 속성으로 읽습니다.

## 6. 이름 규칙

- 컨테이너: `SITE`, `BLDG-<동>`, `BLDG-<층>` (`BLDG-1F`, `BLDG-RF`)
- 요소: `<접두>-<레벨 또는 번호>` — `STR-COL-1 FL`, `C1-3`, `SLAB-2 FL`, `CW-1 FL`, `GR-2 FL`, `ST-1 FL`, `RW`, `ROOF-RF`, `PK-T2`
- 반복 가구: `CH-C1`, `TB-T1` (정의 이름 = 자산 이름)
- asset_id: `<모델>:<class>:<이름>` 소문자, 공백은 `-` (예: `0914:column:c1-1`)
- 금지: `그룹#N`, `fghfghfh` 같은 의미 없는 이름, Layer0 최상위

## 7. 다른 건물에 적용하는 순서

1. 레벨 4개(GL/1F/2F/RF)를 새 값으로 정합니다.
2. SITE: 대지 면 → `retaining_wall` → `stair` → `parking_deck`.
3. BLDG마다 층 컨테이너를 만들고 `column_grid` → `slab` → `curtain_wall` → `glass_railing` → `roof`.
4. 가구·나무·사람은 `place_block`으로만 넣습니다(새로 모델링하지 않음).
5. 덤프(`dump_model.rb`) → 온톨로지 수집 → /review에서 분류 승인.

## 8. 0914 모델 정리 체크리스트 (참고)

- 미사용 정의 59, `<auto>` 재질 28, 빈 태그 43 정리(승인 후)
- 의자·나무·사람을 100면 이하 대체 블럭으로 → 표시 면 약 40% 감소
- 비균일 스케일 33개, 반전 18개 정리
- 난간 높이·주차 경사로 기울기는 실제 도면으로 확인

## 단독주택 창호 자산 (창 · 소방관 진입창 · 루버)

- 입력: `data/sources/sketchup/0914-meeting/openings.json` (run6 읽기 전용 추출, 로컬 경로 제거). 스키마: `schemas/sion-bim-opening-1.schema.json`
- 클래스: `window-louver`를 `window` / `fire-entry-window` / `louver`로 세분화(`data/sources/sketchup/object-subclasses.json`).
- 유형: W1 서측 고창 2400×600(2개) · W2 북측 띠창 5600×600 · W3 동측 미서기 2500×1450 · W4 동측 미서기 3400×1450 · FE1 남측 소방관 진입창 2000×2400(유리 940×1305) · L1 수평 루버 940×2340(살 24개, 간격 100).
- 소방관 진입창 기준은 `data/sources/sketchup/code-refs/kr-fire-entry-window.json`(건축법 제49조제3항, 시행령 제51조제4항, 피난방화규칙 제18조의2)에 원문 요약으로 기록. 카드의 `opening.compliance`는 형상 기반 **추정**이며 항상 `unverified`.
- 재생성: `python scripts/sketchup/build_bim_cards.py` → `python -m sion_ingestion.asset_index build --manifest data/assets/sketchup/_index/manifest.json --library-index-dir data/assets/sketchup/_index/library`
