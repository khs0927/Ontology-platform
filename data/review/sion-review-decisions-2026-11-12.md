# Sion `/review` 판정 기록 — 2026-11-12

메인 PC의 라이브 Sion DB(`D:\SionData\sion.db`)에 쌓여 있던 리뷰 후보를 모두 판정해 **대기 0건**으로 마감한 기록입니다.
판정 API: `POST /api/v1/relations/candidates/bulk` (로컬 전용, 항목마다 `expected_versions` 비교, 사유 필수).
검토자 이름: `dsh-lead (owner authorized bulk completion)` — 오너가 자율 완수를 지시한 세션에서 수행.

## 결과 요약

| 묶음 | 건수 | 판정 | 근거 |
|---|---|---|---|
| SketchUp 0914 분류 후보 (`source_kind=inferred`, `predicate=classified_as`) | 214 | **승인** | 단일 대입 분류. 근거 체인 = `classification.json` + `model_dump.json` + `.skp` (sha256 고정), `properties.basis_ko`에 기하·속성 관측 문장. 저신뢰(co-occurrence) 규칙 0건 |
| 맵 관계 (`source_kind=imported`) | 7 | **거절** | 오너 위임 교차검토(`data/review/sion-map-relation-decisions.json` #53, 2026-10-09)의 결론이 보류 — 관계종류·방향·`role` 불일치. 사유를 각 항목에 그대로 기록 |
| guideline/workflow 링크 (`source_kind=document`, `predicate=derived_from_model`) | 844 | **승인** | 작성된 가이드 문서의 sha256 고정 행 범위(`docs/sketchup/MODELING-GUIDELINES.ko.md`, `docs/sketchup/GROUPING-WORKFLOW.ko.md`), extractor `sion-sketchup-assets/v1`, 신뢰도 0.9. 인용 행을 원문 대조해 지침의 `sion-guide evidence="def:…"` 속성과 일치 확인 |
| 맵 관계 기존 승인분 | 36 | (승인 유지) | 오너 검토(`claude-on-behalf-of-owner@DESKTOP-KTQHS1I`)가 2026-10-09에 이미 승인 |

**합계**: 후보 1,101건 = 승인 1,094 · 거절 7 · **대기 0**.

## 절차

1. 후보는 `properties.candidate = true`이고 `verification_state='unverified'`인 관계이며, `source_kind`가 `inferred`/`imported`/`document`입니다.
2. 대량 판정 전 **근거 확인**: 214건 전부의 증거 행(분류 근거 파일 + sha256 + 행 locator), 저신뢰 판정(`is_low_trust`: co-occurrence 규칙만으로 만들어진 엣지) 0건, 7건 거절 사유(위임 검토 파일의 항목별 이유), 844건 중 표본 2건의 원문 행 대조.
3. 판정 적용: `ids` + `decision` + `note`(필수) + `reviewer` + `expected_versions`(= 현재 `review_rev`). 응답의 항목별 `result`(`applied`/`unchanged`/`conflict`/`not_found`/`not_candidate`/`invalid_id`)를 확인.
4. 검증: 관계·증거 행 상태가 함께 갱신되고, `properties.review`(판정·검토자·사유·시각)와 `properties.review_log`에 감사 항목이 남으며, `review.batch_decided` outbox 이벤트가 발행됩니다.

## 되돌리기

승인·거절은 직접 반대 판정으로 바꿀 수 없습니다(409). `POST /api/v1/relations/candidates/<id>/reopen`에 사유를 넣어 대기 상태로 되돌린 뒤 다시 판정합니다. 되돌린 판정은 `properties.review_history`에 이력으로 남습니다.

## 함께 고친 것

- `source_kind=document` 후보가 목록에서 빠져 있어 "워크플로" 칩이 항상 0이었습니다 → [#137](https://github.com/khs0927/Ontology-platform/pull/137)이 `CANDIDATE_SOURCE_KINDS`에 `document`를 포함하고, 문서 후보가 목록에 뜨고 판정된다는 테스트를 함께 추가했습니다.
- [#139](https://github.com/khs0927/Ontology-platform/pull/139)는 pytest가 오너의 실제 Drive 스토리지 루트(`SION_STORAGE_ROOT`)에 테스트 DB를 export해 `sion-latest.*`를 덮어쓰던 문제(2026-11-11 23:30, 2026-11-12 04:04)를 막고, 복구는 실제 DB 재export로 끝냈습니다(`entities 2290 / relations 7514 / evidence 5744`).

## 관련 이슈

- 이슈 #3(31노드/43관계 맵 import) — 43개 엣지 전부 판정(승인 36 · 거절 7), 종료.
- 이슈 #33(SketchUp/Drive 후속 체크리스트) — 214건 + 844건 판정 반영, 본문 UTF-8 복원 후 갱신.
