<!-- README 스니펫: 아래 '## 생태계 내 역할' 절을 README.md에 그대로 붙여 넣을 수 있습니다. -->

## 생태계 내 역할 (Role in ecosystem)

**지식 — 메인 모노레포**

- Sion API, 지식그래프/GraphRAG, 규제(ArchOntos), AEC(Ontology), GOD-CAD를 한 저장소에 두고, 나머지 저장소와는 버전 고정 계약으로만 연결합니다(`docs/INTEGRATION_CONTRACTS.md`, `packages/core/sion_core/contracts/`).
- CAD 호스트에 대해서는 읽기 전용입니다. 받는 것: `power-cad-execution-receipt/1`, `hs-steel-section-catalog/1`, `korean-land-parcel-analysis/2`, `building-regulation-report/1`, `all-in-cad-dxf-evidence`. 주는 것: AEC REST `/v1/*`, `GET /api/v1/aec/query`.
- `docs/pipeline/REPOS.ko.md`에는 실제 저장소 상태와 다른 행이 있습니다(ECOSYSTEM.md "주의할 사실").

전체 지도: [ECOSYSTEM.md](https://github.com/khs0927/power-cad-mcp/blob/main/docs/ecosystem/ECOSYSTEM.md) · CAD 정리 계획: [CAD_CONSOLIDATION_PLAN.md](https://github.com/khs0927/power-cad-mcp/blob/main/docs/ecosystem/CAD_CONSOLIDATION_PLAN.md) (2026-11-07 기준, 설계안)
