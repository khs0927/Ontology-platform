# PDF 도면 적재 방식 재평가 — 2026-10-03 KST

## 결정

현재 방식은 기본 관측 추출과 임시 조회용 데이터 생성으로는 유효하지만, 완성된 건축 온톨로지/GraphRAG 적재 방식으로 최선이라고 판단할 근거가 없다.
기존 458개 원본 ID / 390개 콘텐츠 해시 / 원본 근거와 v1 결과를 보존한다. 같은 파서로 단순 배치 확대를 하기 전에 페이지별 품질 분류와 한국어 OCR을 검증하고, 새 분석 버전으로 선택 재처리한다.
이 문서는 감사/제안이다. 실제 파서 수정, OCR 모델 설치, v2 재처리, 운영 migration 또는 다른 worker 중단을 실행하지 않았다.

## 검증 기준과 현재 GitHub 상태

- Ontology master 관측 SHA: 742db4b93688c2f989fd6d93676d44c1490c7046.
- [현재 parsers.py](https://github.com/khs0927/Ontology/blob/742db4b93688c2f989fd6d93676d44c1490c7046/src/aec_intelligence/operational/parsers.py), blob b60df64ce826080220a5ad00711fe2b4ccb16319.
- [pdf_drawings.py](https://github.com/khs0927/Ontology/blob/742db4b93688c2f989fd6d93676d44c1490c7046/src/aec_intelligence/operational/pdf_drawings.py), [PDF tests](https://github.com/khs0927/Ontology/blob/742db4b93688c2f989fd6d93676d44c1490c7046/tests/test_pdf_drawings.py).
- 실제 추출 v1은 PR15 병합 SHA b232594bfb391af2853d7b8b31e4a4e741526234를 사용했다. 현재 기본 브랜치 HEAD를 옛 SHA와 동일하다고 보고하지 않는다.
- Exa 4개 검색축, 총 요청 검색결과 18개 후보에서 공식 PyMuPDF/PaddleOCR/Docling 문서를 선택해 본문을 확인했다. 검색 결과에 섞인 비공식 docling.org는 공식 근거로 사용하지 않았다.
- 현 실행에서 OCR/VLM 모델 간 실제 정확도·처리율 비교를 수행하지 않았다. 아래 추천은 코드/실제 산출물 검사와 공식 기능에 근거한 설계 판단이다.

## 실제 산출물 검사

누적 ZIP의 SQLite를 메모리에 열어 확인:
- sources 458개, 고유 해시 390개, Page 2,406개.
- 관계 192,305개 = contains 191,473 + hasTitleBlock 832.
- 객체: Annotation 131,362 / Dimension 30,962 / Document 390 / Grid 660 / Page 2,406 / TitleBlock 832 / Wall 25,251.
- OCR 필요 Page 플래그 591개 (전체 페이지의 약 24.6%). 다른 페이지가 모두 완전하게 추출됐다는 뜻은 아니다.
- integrity_check=ok. 이것은 SQLite 저장 구조 검사이며 도면 의미·치수·벽 분류 정확도 검사가 아니다.
- 현재 PDF 데이터에는 공간의 경계, 벽과 실 연결, 상세도 참조, 프로젝트/단계/개정/법규 연결 등 목표 관계가 아직 구성되지 않았다. 객체·관계 건수를 온톨로지 완성도로 해석하지 않는다.

직전 배치 신규 고유 콘텐츠 106개 / 123페이지를 추가 검사:
- 텍스트 계층 없는 페이지 114개.
- 이미지 항목 있는 페이지 16개; 텍스트와 이미지가 함께 있는 페이지는 이 표본에서 0개.
- 페이지에 이미지가 없다고 OCR 불필요인 것은 아니다.
- 실제 03. 대지종횡단면도.pdf 첫 페이지(Drive ID 13_-0jRLzP8YBROe6hUBDVyImb4ozgKjm)는 벡터 path 2,757개, 텍스트 추출 0, 이미지 항목 없음. 렌더링에서 한글 도로·건축선 표시와 GL 치수가 보였다. 가시적인 문자와 추출 텍스트 계층이 다른 경우를 확인했다.
- 14. 횡단면도.pdf 첫 페이지(1tkRCQyNTm0LXpf2MoRN0lQ8jz2ruFv0K)도 텍스트 추출 0인데 한글 주석·치수·표제란이 보였다. 이미지 항목을 포함하지만 순수 스캔으로 단정하지 않는다.

## 구체적인 한계

1. 혼합 페이지 OCR 누락:
   현재 PDF 분기는 텍스트 block 하나라도 있으면 OCR을 생략한다.
   v1 고정 파서에서 가시적인 raster drawing note와 native 'Page 1'만 넣은 합성 PDF를 실제 실행했다.
   결과: OCR 호출 0, OCR 필요 표시 false, 추출 주석은 Page 1만, raster note 미추출.
   현재 GitHub 코드에서도 같은 페이지 전체 무텍스트 조건을 확인했다.
   이번 실제 123페이지 표본에서 혼합 페이지 누락을 확인했다는 뜻은 아니며, 조건 자체의 재현 가능한 실패 사례이다.
2. 텍스트 없는 벡터 도면:
   path 데이터가 남아도 한글/치수 의미가 자동 복원되지는 않는다. 문자 윤곽으로 보이는 영역도 렌더링 기반 OCR 대상으로 분류해야 한다.
3. 회전·대형 도면:
   현재 무텍스트 페이지는 Matrix(2,2)로 렌더링한다(통상 PDF point 기준 144 DPI). 한글 작은 글자, 90도 회전, 대형 시트에 충분한지 실측하지 않았다.
   페이지/영역 회전, crop/scale 변환행렬을 저장하고 타일 경계의 중복 OCR을 제거해야 한다.
4. 벽/치수 의미:
   PDF Wall은 평행선 규칙의 AI_INFERRED 후보다. 벽의 실제 경계·개구부·실 연결을 확인한 결과가 아니다.
   단일 표제란 축척을 페이지 전체에 적용하면 다중 축척 상세도에 잘못된 길이가 생길 수 있다.
   숫자만으로 mm 단위를 확정하지 않는다. 별도 뷰/축척/단위 증거가 필요하다.
5. OCR 어댑터 버전:
   현재 코드의 show_log/use_angle_cls/ocr(...,cls=True)/옛 중첩 반환 구조는 2.x 스타일이다.
   PaddleOCR 공식 3.x 문서는 비호환 변경과 새 반환 구조를 명시한다. 최신 패키지 설치만으로 실행 보장할 수 없으므로 SDK/모델/어댑터 버전을 고정하고 시험해야 한다.
6. 산출물 보존과 캐시:
   배포 ZIP에는 원본 PDF·원시 벡터·페이지 PNG가 없다. Drive 원본이 변경되면 옛 해시의 원본을 그 ID만으로 다시 가져올 수 있다는 보장이 없다.
   내구성 있는 원본/관측 아티팩트 캐시와 결과 manifest가 필요하다.
   이번 thin wrapper는 기존 SHA가 있으면 옛 결과를 재사용한다. 새 파서/OCR 버전으로 재처리할 때에는 이 조건으로 v2를 생략하면 안 된다.
7. 완료 상태:
   PARSED를 추출 완료/품질 승인/온톨로지 투영 완료/검색 인덱스 완료로 세분화해야 한다.
   warning이 있어도 기본 파싱 성공으로 끝나는 것을 의미 검증 완료로 보고하지 않는다.

## 권장 구조 — 오픈소스 재사용 우선

| 자료/단계 | 권장 처리 | 이유와 경계 |
|---|---|---|
| 원본·버전 | Drive file ID + revision 관측 + SHA-256, 원본 콘텐츠 캐시 | 재현성; 동일 콘텐츠와 프로젝트별 문서 사본의 맥락을 분리 |
| 디지털 PDF | PyMuPDF 텍스트 + path + 이미지 배치 정보 보존 | 원래 좌표/벡터를 OCR로 대체하지 않고 유효한 관측 재사용 |
| 무텍스트/손상/혼합 영역 | 한국어 PP-OCRv5 후보, 회전 교정 + 영역별/타일 OCR | 한국어·숫자 복구, 기존 정상 텍스트 보존; 실제 도면 벤치마크 후 확정 |
| 표·설명서·일람표 | Docling 표/레이아웃/문서 구조 파이프라인 | 건축 선 도면을 일반 문서 Markdown으로만 바꾸지 않음 |
| 도면 의미 | 표제란/뷰/축척/도면번호/상세참조 추출, 규칙 + 선택적 VLM 보조 | 원본 bbox·근거와 연결하고 후보/검증을 분리; VLM을 치수 진실의 근거로 사용하지 않음 |
| DWG/DXF가 존재할 때 | 원본 CAD 직접 파서와 PDF 대응 관계 | 치수/레이어/블록 근거를 우선 활용; 실행 가능한 변환기 및 외부참조 검증 필요 |
| 온톨로지 | Evidence → 후보 Assertion → 검증 상태 → 프로젝트/개정/참조 관계 | raw observation 수와 검증 지식을 분리 |
| 운영 저장·검색 | 기존 PostgreSQL/JSONB + 필요 시 AGE·pgvector, 원본 근거 검색 | SQLite는 휴대형 검증 결과로 유지; 임베딩/GraphRAG는 품질 승인 뒤 파생 인덱스 |

PaddleOCR 기본 중국어/영어 모델 대신 한국어 모델을 명시해야 한다. 공식 모델표의 정확도는 해당 데이터셋 결과이며 사용자 건축도면 정확도 보장이 아니다.
무료 오픈소스 모델은 API 과금 없이 구동할 수 있지만 클라우드 CPU/GPU·원본 보관 비용이나 상시 무료 실행이 확보됐다는 뜻은 아니다. PC/remote 제외 조건을 유지한다.

## 다시 하는 범위와 순서

- 보존: 37,817개 PDF 목록, 458개 원본 ID와 390개 콘텐츠 해시, 정상 원문 추출, 원본 근거, v1 결과.
- 먼저 전 페이지의 text/image/vector/rotation/문자 손상/품질 신호를 다시 분류한다. 591개만 OCR 필요라고 확정하지 않는다.
- 검증용 60페이지를 유형별 10페이지(정상 텍스트/문자 윤곽/스캔·이미지/혼합/회전/다중 축척·표)로 구성하되 중복 유형을 명시한다. 현재 배치에 혼합 표본이 없으므로 다른 원본 또는 회귀 fixture를 사용한다.
- 실제 정답을 확인한 한글 문자열, 도면번호, 치수·단위, 표제란, 상세참조, bbox 위치를 평가한다. 도구별 문자 오류·필드 일치·미검출·추정 오탐, 처리시간/메모리를 비교한다.
- 기존 파서, 새 OCR 보완, 필요한 문서용 Docling을 같은 표본에 비교한다. 벤치마크 없이는 가장 우수한 모델/설정이라고 확정하지 않는다.
- 재추출 key = source_sha256 + parser_commit + OCR_model/version + preprocessing_config_hash + schema_version.
- OCR 누락·손상·품질 실패 페이지와 의미 후보를 v2로 재처리한다. 정상 텍스트/벡터 관측은 재사용한다.
- 프로젝트·개정·상세참조 그래프와 파생 검색 인덱스는 v2 검증 후 별도로 재투영한다. 기존 v1은 비교 기준으로 보존한다.
- 운영 writer/lease 담당자 하나를 확인한 뒤 운영 반영한다. 이 문서는 다른 세션을 멈추거나 운영 DB를 덮어쓸 권한을 대신하지 않는다.

## 공식 근거

- [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html): 전체/이미지 영역 OCR, 텍스트 없는 페이지 및 작은 벡터로 표현된 문자 가능성, OCR 결과 캐싱.
- [PyMuPDF 좌표](https://pymupdf.readthedocs.io/en/latest/page.html): unrotated 기준과 rotation/derotation 변환.
- [PaddleOCR 한국어 PP-OCRv5](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html): 한국어 모델·언어 설정.
- [PaddleOCR 3.x migration](https://www.paddleocr.ai/latest/en/update/upgrade_notes.html): 비호환 변경·새 반환 구조.
- [Docling 공식 프로젝트](https://github.com/docling-project/docling), [DoclingDocument](https://docling-project.github.io/docling/concepts/docling_document/): 텍스트/표/그림/문서 계층과 bbox/provenance.

## 동시 작업 상태

문서 전용 Draft PR17의 새 감사 파일만 생성한다. 기존 코드·기본 브랜치·원본 Drive·운영 DB 변경 없음.
Claude/다른 ChatGPT worker 상태 미확인. 이번 턴에서는 추가 PDF 배치를 적재하지 않았다.
기존 데이터의 정상 보존·운영 미적재 사실은 유지하되, 기존 보고의 객체/관계 수와 DB 무결성을 분석 품질 검증으로 사용하지 말아야 한다.

이전 [458개 체크포인트](2026-10-03-drive-batch03-and-cumulative-458.md).
