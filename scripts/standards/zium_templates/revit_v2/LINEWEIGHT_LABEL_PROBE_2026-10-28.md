# ZIUM Revit v2 — 선 두께 근거 & 레이블 접두사 조사 (2026-10-28)

## 1. 선 두께 (출처: CTB, 추정값 없음)
소스 DXF(src_blocks/*.dxf): `$LWDISPLAY=0`, 객체 lineweight(370) 전부 ByLayer(-1)/Default(-3), 예외 1개(KEYPLAN 0.20mm). → 선 두께는 **색상 종속 CTB**로 결정. `$STYLESHEET`(원본 도면) = `ZIUM_A3(실장님).ctb`.
`ZIUM_A3(실장님).ctb` 펜 테이블 (zlib 해제 후 plot_style lineweight 인덱스 → custom_lineweight_table, ACI = index+1):

| 선 두께 (mm) | ACI 색상 |
|---|---|
| 0.53 | 117, 210 |
| 0.40 | 200 |
| 0.35 | 52 |
| 0.30 | 2, 192 |
| 0.27 | 6, 50 |
| 0.20 | 7, 10, 31, 32 |
| 0.18 | 21, 63, 80, 81, 82 |
| 0.15 | 4, 70, 161 |
| 0.13 | 3, 114 |
| 0.10 | 22, 30, 90 |
| 0.05 | 8 |
| 0.018 | 1, 9, 14, 16, 25, 26, 35, 37, 42, 43, 67, 73, 93, 94, 98, 137, 149, 157, 195, 199, 250–255 |
| 0.09 | 그 외 전부 (5, 11–13, 15, 17–20 …) |

참고 `ZIUM_A3.ctb`: 0.53=210, 0.45=42, 0.40=2, 0.30=6, 0.27=7/50, 0.20=10, 0.18=4, 0.13=3/30, 0.05=1/8/9/26/43/73/144/195/250–255, 0.0=93, 나머지 0.09.

Revit 적용: 선 두께 표(펜 1–16)는 API 설정 불가 → UI `관리 › 추가 설정 › 선 두께`. 위 고유값 13개(0.018~0.53)를 펜에 배정하는 매핑은 실장님 확인 필요(펜 번호 배정은 미결, 임의 지정 안 함).

## 2. 레이블 접두사 "(G.L+ … )"
- Revit 2027.3 `AnnotationLabelParameterFormatting.Prefix/Suffix`: public getter만, setter는 non-public.
- 현재값(ZIUM_레벨헤드): `이름` prefix='' / `입면` prefix='' suffix=''.
- 리플렉션으로 non-public setter 호출 시도(롤백 트랜잭션) → **Revit 프로세스 종료(23:57:34 KST)**, 예외 반환 없음. 다시 시도 금지.
- 결론: 패밀리 편집기 UI에서 수동(레이블 편집 › 접두사 `(G.L+`, 접미사 `)`).
- 템플릿 rte 변경 없음 (백업 `_backup/ZIUM_template_v2_20261028_235408.rte`).

CTB 파일: Drive → `zium-templates/autocad/plotstyles`, `revit/src_blocks` 설치 완료.
