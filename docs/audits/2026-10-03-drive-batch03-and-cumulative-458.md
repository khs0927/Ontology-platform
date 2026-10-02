# PC 없는 Drive 배치 03 — 누적 PDF 458개 (2026-10-03 KST)

사용자 지시: 계속. PC/원격 접속 없이 현재 Drive 연결로 미처리 후보를 읽고 독립 결과를 생성했습니다.

## 실제 처리와 검증

- 이전 임시 작업공간이 정리되어 Library에 저장된 누적 338개 ZIP을 복구했습니다. ZIP CRC 및 ZIP 내부 SQLite 바이트를 메모리에 deserialize하여 무결성을 재확인했습니다. 파일시스템 랜덤 I/O에 의존하지 않았습니다.
- 최신 updated-work-queue.csv에서 PARSED를 제외한 도면 PDF 120개를 선정하고 현재 Drive 메타데이터를 다시 확인했습니다.
- 다운로드 120개, 39,649,711 bytes. 다운로드/최종 파싱 실패 0. 원본 크기 불일치 0, 목록 이후 크기·수정시간 변화 0.
- 배치 내 고유 콘텐츠 115개, 기존 콘텐츠와 SHA-256 동일 9개, 신규 고유 콘텐츠 106개.
- 신규 123페이지 / 객체 3,658개 / 관계 3,556개. 새 OCR 필요 114페이지.
- PDF 기본 파서 SHA: b232594bfb391af2853d7b8b31e4a4e741526234. 기존 개발 코드 변경 없음.
- 독립 통합 보조 스크립트의 초기 관계 INSERT 컬럼 수 오류를 발견해 수정 후 기존 기준 ZIP부터 전 배치를 재실행했습니다. 초기 실행 결과는 저장·공유하지 않았습니다. 최종 실패 목록은 빈 배열입니다.
- 최종 SQLite 저장 바이트를 다시 열어 integrity_check=ok, FK 위반 0, 원본 해시 연결 누락 0.
- 기존 객체 188,205개 내용을 그대로 보존한 것을 비교 검증했습니다. 신규 비유한 bbox 0, source_hash 불일치 0.
- FTS '평면도' 검색 893개. 의미 분류 정확도/BIM 세계 좌표 검증 결과는 아닙니다.

## 최신 누적 결과

| 항목 | 값 |
|---|---:|
| 성공 처리 원본 Drive PDF ID | 458 |
| 고유 콘텐츠 | 390 |
| 페이지 | 2,406 |
| 객체 / 관계 | 191,863 / 192,305 |
| OBSERVED / AI_INFERRED | 134,158 / 57,705 |
| OCR 필요 페이지 | 591 |
| 전체 PDF 목록 | 37,817 |

목록 상태: PARSED 458 / ARCHITECTURAL_CANDIDATE 11,718 / SCOPE_REVIEW_REQUIRED 24,677 / LARGE_TRANSFER_REQUIRED 944 / EMPTY 18 / NON_PDF_CONTAINER 2.
목록은 2026-10-02 PDF 검색 관측이며 이번 120개를 현재 메타데이터로 확인했습니다. 모든 파일을 이번에 다시 census한 결과가 아닙니다.
PARSED는 기본 추출 성공이며 OCR 완료를 뜻하지 않습니다. 591개 Page의 ocr_required 플래그를 직접 확인했습니다. Docling 표 재구성과 한국어 OCR은 미완료입니다.

## 실제 결과 파일

- [누적 PDF 458개 통합 그래프](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 95,478,294 bytes, ZIP CRC 통과.
- 다음 배치는 이 ZIP의 **updated-work-queue.csv** 및 **cumulative-checkpoint.json**을 기준으로 재개하세요. 338개 시점의 목록을 사용하면 중복 처리가 생깁니다.
- SQLite, sources.json, parse_results.json, batch-provenance.json, batch-parse-results.json, graph-verification.json, queue-status-summary.json, failures.json을 포함합니다.
- 재개 안내 NEXT_BATCH.ko.md, 이번 독립 통합 process_and_merge.py, 고정 파서 소스 pinned/도 포함했습니다. 스크립트는 연결된 Drive 다운로드나 상시 worker를 자동 실행하지 않습니다. 실제 다운로드 경로 manifest와 기준 ZIP이 필요합니다.
- 원본 PDF·원시 벡터·PNG는 중복 포함하지 않았습니다. 원본 ID/SHA-256/수정시간/페이지/bbox/추정 상태는 보존했고 고정 파서로 재생성할 수 있습니다. 좌표는 PDF_POINTS입니다.
- sources.sha256=objects.document_hash로 원본 사본을 연결합니다. 동일 콘텐츠 사본의 프로젝트가 같다고 가정하지 마세요.

## 동시 작업 보호 및 미완료 범위

- 원본 Drive·기존 결과·기존 개발 코드·운영 DB를 덮어쓰지 않았습니다.
- 문서 전용 기존 Draft PR #17에 새 문서만 추가합니다. 자동 머지하지 않습니다.
- Claude/다른 ChatGPT의 로컬 미커밋 변경과 worker 상태는 미확인입니다. 다른 worker가 없다고 가정하지 마세요.
- 운영 PostgreSQL/AGE 쓰기, LightRAG/임베딩, 상시 클라우드 worker 배포는 실행하지 않았습니다.
- 전체 약 34,000개 건축도면 적재 완료가 아닙니다. 전 PDF 목록에는 비건축 자료도 있고 DWG 등 다른 형식은 포함되지 않습니다.
- 남은 범위: 후보 PDF 처리, 범위 검토, 대용량 파일 전송, DWG 변환, 한국어 OCR, 목적 DB와 장기 실행 위치 연결.

이전 인계: [누적 338개](2026-10-02-drive-batch02-and-cumulative-338.md).
