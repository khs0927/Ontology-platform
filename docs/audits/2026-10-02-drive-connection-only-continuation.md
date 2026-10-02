# Google Drive 연결만으로 이어간 처리 — 2026-10-02

사용자 지시: **PC 없이 진행 @Google Drive**. PC 접속/원격/로컬 Windows 실행을 사용하지 않았습니다.

## 새로 완료한 것

1. 접근 가능한 Drive의 비휴지통 application/pdf 파일을 페이지 끝까지 검색했습니다.
   - 고유 Drive PDF ID **37,817개**.
   - 메타데이터상 원본 크기 합 **158,534,185,215 bytes** (약 158.5GB).
   - 이는 **전체 건축도면 37,817개**라는 의미가 아닙니다. DWG/DXF/SKP/HWP 및 Google-native 문서는 이 목록에 포함되지 않습니다.
   - Drive가 수집 중 변경될 수 있으므로 변경 감지 재수집은 별도 필요합니다. 서비스 계정/PC 로그인 없이 현재 연결로 얻은 목록입니다.
2. 파일별 처리 상태와 원본 ID/수정시간/부모 ID/원본 URL/알려진 SHA-256을 CSV와 JSONL로 저장했습니다.
3. 최근 구조도면 묶음 **신진유압 화목동 698-14 신축공사 2026.06.08** PDF 23개를 실제 다운로드/파싱했습니다.
   - 23개 모두 성공, 44페이지.
   - 객체 4,955개 / 관계 4,956개.
   - OBSERVED 3,709 / AI_INFERRED 1,246.
   - Annotation 3,642 / TitleBlock 24 / Dimension 592 / Grid 38 / Wall 592.
   - 텍스트 없는 페이지 0.
   - 별도 SQLite 저장 후 integrity_check=ok, FK 위반 0, 저장 객체 4,955 재확인.
   - 기존 처리 자료와 SHA-256 겹침 0.
4. 기존 195개 PDF 결과와 새 구조도면 결과, 전체 PDF 목록을 Google Drive에 **새 파일**로 저장했습니다. 메타데이터 readback으로 파일 ID/크기를 확인했고 세 파일 모두 shared=false입니다.

## 누적 실제 처리와 미완료

| 항목 | 수치/상태 |
|---|---|
| 처리한 Drive PDF 원본 | **218개** (기존 195 + 신규 23) |
| 고유 콘텐츠 문서 | 208개 |
| 페이지 | 2,186 |
| 객체 / 관계 | 181,999 / 182,574 |
| 운영 PostgreSQL/AGE 적재 | 실행하지 않음 |
| LightRAG/임베딩 | 실행하지 않음 |
| 한국어 OCR | 기존 426페이지 필요 상태 유지 |
| DWG | 기존 후보 954개의 네이티브 변환 미완료 |

전체 PDF 상태:
- PARSED: 218
- ARCHITECTURAL_CANDIDATE: 11,958
- SCOPE_REVIEW_REQUIRED: 24,677
- LARGE_TRANSFER_REQUIRED: 944
- EMPTY: 18
- NON_PDF_CONTAINER: 2

후보 분류는 **파일명 휴리스틱**입니다. 문서 내용 기반 확정 분류, 큐 실행 승인, 실제 파싱 또는 운영 적재 완료를 뜻하지 않습니다. 중립적인 파일명은 부모 프로젝트/본문을 확인해 건축 범위에 포함해야 합니다. LARGE_TRANSFER_REQUIRED는 현재 32MiB 전송 제한에 대한 상태이며 건축 범위 확인은 따로 필요합니다.

## Claude가 읽을 실제 결과

- [기존 PDF 195개 검증된 그래프](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 83,196,603 bytes
- [PDF 37,817개 목록·처리 상태](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 4,704,046 bytes
- [신규 구조도면 PDF 23개 그래프](https://drive.google.com/file/d/PRIVATE_DRIVE_ID/view?usp=drivesdk) — 2,358,587 bytes

패키지 안의 자료:
- 목록 패키지: drive-pdf-work-queue.csv, catalog-summary.json, drive-pdf-inventory.jsonl.
- 신규 그래프: ontology-staging.sqlite, sources.json, totals.json, parse_results.json, graph-verification.json, README.ko.md.

SQLite는 독립적인 처리 결과입니다. 운영 스키마와 동일하지 않습니다. 원본 PDF와 원시 벡터/PNG는 중복 포함하지 않았고, 원본 ID/해시/페이지/bbox 및 추정 상태를 보존했습니다. 좌표는 PDF_POINTS입니다. 원본은 Drive에서 다시 가져올 수 있습니다.

## 충돌 방지와 실행 경계

- 기존 원본 파일·폴더·공유 설정을 변경하지 않았습니다. 결과는 새 파일로 저장했습니다.
- Claude/다른 ChatGPT 개발 브랜치와 운영 DB에 쓰지 않았습니다.
- 파서는 Ontology PR #15 병합 SHA b232594bfb391af2853d7b8b31e4a4e741526234로 고정했습니다.
- 이 인계도 문서 전용 Draft PR #17에 새 파일만 추가합니다.
- 다른 세션의 worker 실행 여부는 관측하지 않았습니다. 실제 대량 적재를 시작하기 전에 작업 소유권 하나를 정하고 SHA-256으로 멱등 처리하세요.
- CSV는 **처리 상태 목록**이며, 살아 있는 장기 worker나 자동 실행 스케줄을 생성한 것은 아닙니다.
- PC는 필요 없지만, 장기 연속 처리/운영 반영을 맡을 클라우드 실행 위치와 목적 DB는 아직 연결되지 않았습니다. 현 연결로 직접 PDF를 처리할 수 있다는 사실과 상시 대량 처리 배포 완료를 구분하세요.
- 남은 자료 전체가 적재 완료된 상태로 보고하면 안 됩니다. 앞선 비원격 문서의 1,000개 폴더 제한은 DWG 등 전체 형식 확인에는 여전히 적용되지만, 이번 PDF 검색은 페이지를 끝까지 따라 범위를 확대했습니다.

기존 검증: [비원격 처리 인계](2026-10-02-no-remote-drive-processing-handoff.md), [저장소 감사](2026-10-02-chatgpt-ontology-powercad-verification.md).
