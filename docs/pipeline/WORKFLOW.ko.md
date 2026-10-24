# 4단계 건축설계 워크플로

단위·포맷·좌표는 `지침/20_CAD_교환_계약.md`를 따른다: 경계 단위 mm(SketchUp 내부 inch/UI mm, site-pipeline m·EPSG:5186),
2D 허브 DWG(mm), 3D 허브 IFC4 RV(mm), SketchUp에 절대 EPSG 좌표 금지(로컬 원점 + Geo-location).

## 1단계 — 대지 분석 + 한국 건축법규 분석
- 도구: site-pipeline-mcp(+korean-site-core), korean-law 라우터(korean-law-mcp), permit-review-mcp, archhub-mcp, korean-land-mcp.
- 입력: 주소/PNU. 출력: 필지 경계(GeoJSON, EPSG:5186), 용도지역·지구, 건폐율/용적률, 도로, 지형(LandXML/CSV), 법규 검토서.
- 절차: PNU 확정 → V-World 필지·용도(키는 `doppler run`) → 토지이음 중첩규제 → 법령 조문 수집(article_retrieved) →
  적용성(applicability) 판정 → jev 4단계 검증 → 건축사 최종판단은 사람이 한다(`지침/19_건축허가_법규검토_완벽지침.md`).
- 지형: V-World 공개 API에는 DEM/등고선이 없다. NGII 수치지형도 v2(5 m 등고선) 또는 5 m DEM 파일 → contours_to_landxml/dem_to_landxml.
  임시로 Copernicus 30 m(신뢰도 낮음).
- LandXML ≤20,000점/파일, Revit import 10,000점 감축.

## 2단계 — SketchUp 모델링 (매스·대지)
- SketchUp 2025 + 플러그인: sketchup-mcp2 v0.4.0 / MCPforSketchUp(포트 9876), hueflow-sketchup-mcp(포트 8080). 포트 변경 금지.
- 작도 실행: Claude CLI(Pro 로그인, 무료)로 MCP 호출. 지형은 `data/sites/<site>/terrain_local_m.obj` 또는 Ruby 빌드 스크립트.
- 규칙: `docs/sketchup/MODELING-GUIDELINES.ko.md`, `GROUPING-WORKFLOW.ko.md`(태그·그룹 구조), 로컬 원점, mm 템플릿.
- 산출: .skp, Revit행 DWG/IFC(Internal/Project Base Point 좌표). SKP-native는 매스→Revit doc.Import 전용.

## 3단계 — Revit BIM
- Revit 2027 (`E:\Program files\Revit 2027`), Revit MCP 123 tools(경계 단위 mm).
- 선행: SHARED 좌표 + Survey Point를 EPSG:5186 격자에 정렬(revit_get_project_coordinate_system 점검). 회전각(True/Project North) 확정 전 왕복 금지.
- 입력: SketchUp IFC/DWG 또는 SKP 매스, LandXML 지형. 출력: RVT, 시트/뷰 DWG(mm), IFC4 RV.
- 주의: RVT 2027 → SketchUp Trimble Importer 불가(≤2025) → DWG/IFC 경유만.

## 4단계 — 최종 도면 (power-cad-mcp, 하우스 스타일)
- power-cad-mcp가 메인. all-in-cad는 `power-cad-mcp\dist\helpers\all-in-cad` helper로 병합되어 있고 단독 서버는 비활성.
- HS-CAD 미사용, xicad는 자산 단계로 이연.
- 입력: Revit DWG(mm). 출력: 하우스 스타일 도면(DWG, 헤드리스 폴백은 ezdxf DXF). Sion은 CAD 변경을 실행하지 않는다(근거만).

## 검증 게이트
- 핵심 판단(제외/병합/좌표 확정/법규 적용성)은 jev(jev_decide/jev_verify)로 판정 후 기록.
- 이전 차수 결과를 먼저 열어 대조한 뒤 작성(사용자 최우선 원칙).
