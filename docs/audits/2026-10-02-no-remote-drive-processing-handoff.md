# 비원격 Drive 도면 처리 및 Claude 인계 — 2026-10-02

사용자 최종 지시: **리모트 없이 진행**. 이 단계에서는 PC 원격 실행·접속을 사용하지 않았습니다. 연결된 Drive 읽기와 별도 작업 공간에서 실제 처리를 수행했습니다.

## 완료 범위

| 항목 | 실제 결과 |
|---|---|
| Ontology PR #15 | 병합 완료, merge SHA `b232594bfb391af2853d7b8b31e4a4e741526234` |
| 사용 파서 | 위 SHA의 parsers.py / pdf_drawings.py / classifier.py / dxf.py / cair.py |
| 다운로드 PDF | 197개, 575,893,295 bytes |
| 해시 중복 제거 | 고유 콘텐츠 187개, 중복 원본 10개 |
| 파싱 성공 | Drive 원본 195개 / 고유 문서 185개 |
| 추출 | 2,142페이지, 객체 177,044개, 관계 177,618개 |
| 객체 상태 | OBSERVED 126,066 / AI_INFERRED 50,978 |
| 상세 객체 | Annotation 123,739 / TitleBlock 759 / Dimension 28,834 / Grid 353 / Wall 21,032 |
| 별도 적재 | SQLite 그래프 + FTS5 검색 생성, 운영 PostgreSQL/AGE와 분리 |
| 저장 후 검사 | integrity_check=ok, FK 위반 0, 객체 177,044 재확인 |
| 추가 실제 검사 | 비유한 bbox 0, source_hash 불일치 0, '평면도' FTS 검색 677개 |
| 패키지 | `ontology-drive-no-remote-stage-20261002.zip`, 83,196,603 bytes, CRC 검사 통과, 사용자에게 전달/저장 완료 |

**전체 약 34,000개 완료가 아닙니다. 운영 DB/AGE/LightRAG에 적재하거나 임베딩한 결과도 아닙니다.**

SQLite 컬럼과 JSON 증거, 원본 Drive ID/SHA-256, 처리 상태를 보존했습니다. source PDF와 대용량 원시 벡터/PNG를 패키지에 중복 포함하지 않았습니다. 페이지/bbox/분류 근거로 원본에 접근하며 원시 벡터는 지정 커밋으로 재생성합니다. PDF_POINTS를 세계 좌표나 BIM 실형상으로 해석하지 마세요.

## 데이터 범위와 실제 차단 항목

- 회사 CAD/도면의 선택한 8개 루트에서 127개 하위 폴더, 3,660개 항목을 목록 확인했습니다. 이는 전 Drive census가 아닙니다.
- `단위세대` (`PRIVATE_DRIVE_ID`) 폴더는 list_folder가 1,000개에서 잘립니다. 이 도구에는 다음 페이지 인자가 없습니다. 상한을 늘리는 시도도 API 최대 1,000으로 거부됐습니다.
- 이 폴더의 PDF는 document 검색의 next_page_token을 끝까지 따라 2페이지/183개를 확인했고 새 PDF는 없었습니다. DWG 전체를 확인했다는 근거로 사용하지 마세요.
- 별도 도면(프로젝트별)/도면(용도,재료)/도면(도면별)에서는 일부 파일이 0바이트였습니다. PDF와 DWG 각각 실제 다운로드 크기도 0으로 확인했습니다. 회사 폴더의 비어 있지 않은 도면과 구분해야 합니다.
- 패키지 inventory의 파일 상태: PARSED 195 / NON_PDF_CONTAINER 2 / TRANSFER_LIMIT 2 / NATIVE_CONVERTER_REQUIRED 954 / EMPTY_SOURCE 3 / AUXILIARY_NOT_PARSED 2,394.
- NATIVE_CONVERTER_REQUIRED는 실제 크기가 있는 DWG 후보입니다. 현재 환경에 ODA/LibreDWG 실행 파일이 없으므로 내용 추출을 수행하지 못했습니다. DWG 표본은 실제 328,704 및 114,945 bytes, AC1021/AC1024 헤더 확인.
- 다운로드 PDF 2개는 `DOCUMENT SAFER V2010 R2` 헤더, PDF signature 없음. 원본을 보존했고 표준 PDF 파서 실패로 기록했습니다.
  - `EE-406~409 단위세대 전열설비 평면도 Model.pdf`: Drive ID `PRIVATE_DRIVE_ID`, 57,895 bytes.
  - `51_TYPE 단위세대 SHOP_220105-시공치수도면 (일반 + 주거약자) Model.pdf`: `PRIVATE_DRIVE_ID`, 213,799 bytes.
- 32MiB 초과 전송 보류:
  - `allplan(건축).pdf`: `PRIVATE_DRIVE_ID`, 39,997,802 bytes.
  - `명지대역 네스트프라임 더파크_POP시안.pdf`: `PRIVATE_DRIVE_ID`, 36,856,548 bytes.
  - 제공된 전송 참조로 추가 다운로드도 시도했으나 HTTP 오류였습니다. 성공으로 집계하지 않았습니다. 임시 다운로드 URL은 문서/패키지에 없습니다.
- 텍스트 없는 426페이지는 OCR_REQUIRED. PaddleOCR 미설치이며 Tesseract는 eng/osd만 있어 한국어 OCR 완료로 집계하지 않았습니다. Docling도 없어 표 재구성 미완료입니다.

## PC 원격 없이 전체 적재를 이어갈 경로

| 방법 | 반영/상태 | 남은 조건 |
|---|---|---|
| 연결된 Drive → 현재 독립 파서 | 위 PDF를 실제 처리/별도 그래프 적재 | 현재 도구의 대용량·DWG 페이지 제한 |
| 지속 가능한 클라우드 worker + rclone OAuth | 기존 Ontology census/enqueue/worker와 연결하는 우선 경로 | 실행 위치, Drive OAuth 연결, 내구성 있는 저장소/운영 DB 접속 |
| 서비스 계정 → 허용된 Drive 폴더 | 폴더 범위를 명시해 접근 가능 | 계정 키와 대상 폴더 권한; PC 원격은 필요 없음 |
| GitHub Actions 배치 | 독립 브랜치 workflow_dispatch 방식 검토 가능 | Drive 자격 정보, DWG 변환기, 외부 영속 DB/아티팩트; 임시 CI DB를 운영 DB로 오인 금지 |
| 원본 프로그램의 표준 PDF/DXF 내보내기 | 비표준 컨테이너/변환 실패 파일의 대안 | 사용자에게 허용된 원본 프로그램의 정상 내보내기 |

현재 환경의 `AEC_DATABASE_URL`이 설정되지 않았고 운영 DB 실행도 없습니다. 새 클라우드/CI 실행이나 유료 API/LLM 호출을 시작하지 않았습니다. 이 문서는 준비 상태를 설명하며 위 경로가 배포됐다는 의미가 아닙니다. 전체 적재는 클라우드 실행 위치·목적 DB·지속 Drive 인증·DWG 변환기가 확보돼야 실제로 이어갈 수 있습니다.

## 동시 작업과 재검증

- 기존 Claude/ChatGPT 개발 코드·브랜치를 수정, rebase, force-push하지 않았습니다. 원본 Drive/운영 DB/CAD에 쓰지 않았습니다.
- 이 인계는 문서 전용 `docs/chatgpt-audit-20261002-1105-e92060` / [Draft PR #17](https://github.com/khs0927/Ontology-platform/pull/17)에 새 문서만 추가합니다. 자동 머지 금지.
- 다른 세션이 실행 중일 수 있습니다. 다른 worker가 없다고 가정해 중복 실행하지 마세요. 운영 writer 하나가 작업 소유권을 가진 뒤 SHA-256 멱등 큐·체크포인트로 재개해야 합니다.
- SQLite는 표준 휴대형 검증/임시 그래프입니다. 운영 PostgreSQL 스키마와 동일하지 않으며 자동 덮어쓰기/임의 SQL migration에 사용하지 마세요.
- 확인 HEAD: Ontology `b232594…`, power-cad-mcp `ce392f9…`, Ontology-platform `98fb958…`.
- platform은 기존 검증 SHA `7ec50e0…`에서 Hindsight advisory memory 추가 SHA `98fb958…`로 이동했습니다. 해당 SHA의 Tests CI 성공: https://github.com/khs0927/Ontology-platform/actions/runs/36999380439
- 추가된 advisory_memory.py, run_hindsight_memory.py, test_advisory_memory.py 3개는 고정 SHA로 읽어 Python 정적 파싱 오류 0을 확인했습니다. 이 환경에서 전체 pytest를 실행한 결과는 아닙니다. Hindsight advisory 메모리를 정식 도면 지식/CAIR로 자동 승격하지 마세요.
- 초기 24개 저장소 감사와 운영 API 인증/DB fallback/CAD 원본 identity 검토 항목은 [기존 검증 문서](2026-10-02-chatgpt-ontology-powercad-verification.md)를 이어서 읽으세요.

사용자가 제공받은 패키지에는 README, SQLite, queries.sql, sources/inventory, 집계와 검사 결과가 있습니다. Claude의 패키지 자동 접근을 가정하지 말고 사용자가 제공한 실제 파일로 작업하세요.
