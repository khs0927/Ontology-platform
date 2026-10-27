# 울산 울주군 웅촌면 고연리 1525 — 대지·지형 분석 (2026-10-23)

| 항목 | 값 |
|---|---|
| PNU | 3171034026115250000 |
| 좌표계 | EPSG:5186, 로컬 원점 E 395925 / N 319220 (SketchUp·Revit 형상은 이 원점 기준 로컬, 단위 m→SketchUp mm 템플릿) |
| 지형 출처 | Copernicus GLO-30 DSM(30 m) → 수관 보정 6 m(위성 식생 비율 가중) → 5 m 격자 보간 |
| 범위 | x −270~+330 m, y −280~+320 m (121×121, 약 600 m 사방) |
| 신뢰도 | **낮음** (30 m DSM, 수관 보정 가정, RMS 4.3 m) |

## 절토 추정 (평탄 패드 = 주변 20~70 m 링에 맞춘 평면, 필지 내부 0.5 m 격자)
- 절토 면적 1,137 m², 평균 절토 6.23 m, 최대 11.09 m, **절토량 약 7,084 m³**
- 성토 면적 120.5 m², 성토량 약 158 m³, 최대 3.21 m
- 호수(저수지) 수면 z ≈ −13.85 m (패드 기준), 수목 1,940주(소나무/활엽 분류)
- 결론: 기존 추정(평균 ~6 m / ~7,100 m³)과 동일. V-World 키가 Drive에 없고(Doppler에만 존재),
  V-World 공개 API에는 DEM·등고선 레이어 자체가 없어 실측 표고로 갱신하지 못했다.

## 파일
| 파일 | 용도 |
|---|---|
| `terrain_grid_local_m.csv` | x,y,z (m, 로컬) — QGIS/Civil/스크립트 입력 |
| `terrain_local_m.obj` | 지형 TIN(m) — SketchUp/Rhino import (가져올 때 단위 m 지정) |
| `site_data_v2.json` | 격자·호수·수목·절토 통계 — `scripts/site/goyeon_build_site_v2.rb` 입력 |
| `cut_plane.json` | 패드 평면 계수 |

## 정밀화 경로 (PC 복귀 후)
1. NGII 국토정보플랫폼에서 해당 도엽 수치지형도 v2(등고선 5 m·표고점) 또는 5 m DEM 다운로드 → site-pipeline `contours_to_landxml`/`dem_to_landxml`.
2. `doppler run ... python scripts/site/fetch_vworld_goyeon.py` 로 지적·용도지역·도로 레이어 수집(표고 없음).
3. 격자 재생성(`scripts/site/goyeon_terrain_v2.py`의 dsm()을 DEM으로 교체, 수관보정 CAN=0) → 절토 재계산.
4. 인허가/개발행위 수준에서는 현황측량 성과가 유일한 1 m 이하 정밀도 경로.
