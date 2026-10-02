# PC 없는 Drive 배치 02와 누적 통합 그래프 — 2026-10-02

이번 사용자 지시: 계속. 앞선 PC/리모트 제외 조건을 유지했습니다.

## 실제 새 처리

- 미처리 평면도·입면도·단면도 등의 PDF **120개**를 현재 Drive 연결로 다운로드했습니다.
- 다운로드 실패 0, 실제 크기 불일치 0, 이전 목록과 크기 변화 0.
- 해시 기준 배치 내 고유 콘텐츠 **77개**. 43개는 동일 콘텐츠 복사본입니다.
- 77개 모두 파싱 성공: 98페이지, 객체 6,239개, 관계 6,207개.
- 텍스트 없는 **52페이지는 OCR_REQUIRED**로 남겼습니다.
- OBSERVED 3,165 / AI_INFERRED 3,074. bbox 비유한 값 0 / source_hash 불일치 0.
- 배치 SQLite 저장 후 integrity_check=ok, FK 위반 0, 객체 6,239 재확인.
- 이전 처리 콘텐츠와 동일한 해시 1개가 있어 누적 객체/관계/페이지에 중복 가산하지 않았습니다.

## 누적 통합 결과

기존 결과와 이번 배치를 한 개의 독립 SQLite 조회용 그래프로 통합했습니다. 원본 ID는 별도로 보존하고 동일 콘텐츠 해시는 앞선 관측을 대표 데이터로 유지했습니다.

| 항목 | 중복 제거 후 값 |
|---|---|
| 성공 처리 Drive PDF 원본 ID | **338개** |
| 고유 콘텐츠 | **284개** |
| 페이지 | **2,283** |
| 객체 | **188,205** |
| 관계 | **188,749** |
| OBSERVED / AI_INFERRED | 132,938 / 55,267 |
| 누적 OCR 필요 페이지 | **477** |
| 저장 후 검사 | integrity_check=ok, FK 위반 0 |
| 원본 해시 연결 누락 | 0 |
| 실제 FTS '평면도' 검색 결과 | 813개 |

이것은 원본 파일 338개 모두의 OCR 및 의미 검증 완료를 뜻하지 않습니다. 기본 파서가 PDF 페이지/텍스트 계층/벡터 후보를 추출한 상태입니다. 세계 좌표/BIM 실형상이나 규칙 준수 판정을 자동 확정하지 않았습니다.

### 통합 파일과 새 작업 목록

- [누적 PDF 338개 통합 그래프](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 93,650,350 bytes, ZIP CRC 검사 통과.
- [이번 120개만의 배치 결과](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 5,306,285 bytes.
- 통합 패키지: ontology-staging.sqlite, sources.json, parse_results.json, graph-verification.json, cumulative-checkpoint.json, updated-work-queue.csv, queue-status-summary.json, README.ko.md.
- 좌표는 PDF_POINTS, 원본 ID/SHA-256/수정시간/페이지/bbox 및 추정 상태를 보존했습니다. 원본 PDF·원시 벡터/PNG는 중복 포함하지 않았고 Drive 원본과 고정 파서로 재생성할 수 있습니다.
- 통합 SQLite에서 sources.sha256=objects.document_hash로 여러 원본 사본을 연결합니다. 동일 콘텐츠 사본들이 동일 프로젝트에 속한다고 추정하지 마세요.

접근 가능한 PDF 37,817개의 최신 처리 상태:
PARSED 338 / ARCHITECTURAL_CANDIDATE 11,838 / SCOPE_REVIEW_REQUIRED 24,677 / LARGE_TRANSFER_REQUIRED 944 / EMPTY 18 / NON_PDF_CONTAINER 2.

기존 218개 처리 시점의 CSV 대신 **이번 통합 파일의 updated-work-queue.csv**를 이어서 사용해야 재처리 중복을 피할 수 있습니다. PARSED는 OCR 완료를 뜻하지 않으며 별도 ocr_required_pages 열로 보류 페이지를 구분했습니다. 후보는 파일명 휴리스틱이고 확정 건축 분류가 아닙니다.

## 동시 작업 보호

- 원본 Drive·기존 결과 파일·기존 개발 코드·운영 DB를 덮어쓰지 않았습니다.
- Claude/다른 ChatGPT의 실제 worker 상태를 관측하지 못했습니다. 다른 실행이 없다고 가정하지 마세요.
- 파서 SHA: b232594bfb391af2853d7b8b31e4a4e741526234.
- 문서 전용 Draft PR #17에 새 문서만 추가합니다. 자동 머지하지 않습니다.
- 독립 SQLite는 운영 PostgreSQL/AGE 스키마와 동일하지 않습니다. 운영 DB 쓰기/LightRAG/임베딩/상시 worker 배포는 실행하지 않았습니다.
- 전체 약 34,000개 도면을 적재 완료한 것이 아닙니다. 전 PDF 목록 37,817개에는 비건축 자료도 있고 DWG 등 다른 형식은 포함되지 않습니다.
- DWG 변환, 대용량 전송, 한국어 OCR, 장기 클라우드 실행과 목적 DB 연결은 여전히 남아 있습니다.

앞선 맥락: [Drive 연결 인계](2026-10-02-drive-connection-only-continuation.md), [비원격 파서 인계](2026-10-02-no-remote-drive-processing-handoff.md).
