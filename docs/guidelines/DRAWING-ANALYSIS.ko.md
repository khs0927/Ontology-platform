# 도면 분석(AEC 온톨로지) 운영·에이전트 지침

작성: 2026-10-09 (Asia/Seoul). 대상: 사람 운영자와 에이전트. 상위 규칙은 루트 [`AGENTS.md`](../../AGENTS.md),
작업 방식은 [`AGENT-WORKFLOW.ko.md`](AGENT-WORKFLOW.ko.md)입니다. 이 문서의 수치는 **작성 시점 스냅샷**이며,
인용하기 전에 반드시 다시 조회합니다(4.4절).

---

## 1. 지금 무엇에 답할 수 있고, 무엇에 답할 수 없는가

기준일 2026-10-09 관찰값:

| 항목 | 값 |
|---|---|
| 큐 | QUEUED 21,726 / SUCCEEDED 691 / FAILED 0 |
| 적재된 문서(`documents`) | 674 |
| 큐 작업 중 `G:\내 드라이브` 원본 비중 | 약 85% |
| 적재 게이트 | 가용 RAM >= 2048MB, workers=1 |

**전체 적재는 끝나지 않았습니다**(SUCCEEDED 691건 대 QUEUED 21,726건). 작업 수(jobs), 적재 문서 수(documents),
KG `Drawing` 노드 수는 서로 다른 분모입니다(같은 문서 재적재, 별칭 중복). 한 숫자를 다른 숫자 자리에 쓰지 않습니다.
"FAILED 0"은 `state='FAILED'` 조건 안에서만 참입니다. 2026-10-05 감사(FINDINGS.md Wave 2)에서 `stage='failed'`인데
`state=SUCCEEDED`인 행, lease 만료 재시도, 문서 없는 ingestion 이벤트가 확인됐습니다.

### 답할 수 있는 것 (적재된 문서 범위 안에서만)

- 적재된 도면의 객체 종류별 개수(벽/문/창/실/기둥/보 등), 레이어, 블록 정의와 사용 횟수, 층 정보.
- 도면 분류(평면도/상세도/단면도/입면도/구조도/일람표/시방서 등)와 시트별 도면번호·도면명·축척 **(추출된 경우)**.
- 객체의 그래프 이웃(층, 실, 호스트 벽, 시트, 블록 정의)과 하이브리드(어휘+벡터+그래프) 검색.
- 인용(`[C#]`: 문서·레이아웃/시트·객체 id·bbox)이 붙은 Graph RAG 답변. 근거가 없으면 `refused: true`.
- 객체 id를 열린 AutoCAD 도면의 handle로 대응(`ontology_locate`, 읽기 전용).

### 답할 수 없는 것 / 해서는 안 되는 것

- **아직 적재되지 않은 도면**(큐 21,726건, 특히 `G:` 원본)에 대한 주장. "없다"가 아니라 "아직 적재 전"입니다.
- 현장/프로젝트 전체에 대한 완결적 통계(총 도면 수, 전체 객체 수, 누락 여부). 모집단이 불완전합니다.
- **정확도 주장**("도면번호 정확도 n%"). 현재 평가는 존재 적중(presence)이며 정밀도가 아닙니다(5절).
- 정본(canonical) 도면 상태. Sion/온톨로지 결과는 `canonical:false, read_only:true`인 **근거**일 뿐이며,
  실제 도면 상태는 열린 CAD에서 `cad_*` 도구로 재확인합니다.
- CAD 쓰기 실행 권한 판단. Sion은 CAD를 수정하지 않으며 네이티브 호스트 검증은 `UNVERIFIED_NATIVE`입니다
  ([`verification-boundary.md`](../../packages/aec/docs/verification-boundary.md)).
- 법규 적합 판정(`packages/regulation` 영역이며 이 문서의 범위가 아님).

---

## 2. 파이프라인 단계, 명령, 게이트, 증거 파일

흐름: **파싱 -> 분석 -> 지침/메모리 -> DB -> 검증**. 운영 파이프라인 명령은 보관된 `khs0927/Ontology`
체크아웃(운영 PC의 `C:\CODE\Ontology`)의 `docs/PIPELINE.ko.md`, `docs/OPERATIONS.ko.md` 기준입니다.
모노레포 전환(`switch-to-monorepo.ps1`) 전까지는 그 체크아웃에서 실행하고, 경로는 PC마다 다를 수 있으니 실행 전에 확인합니다.

### 2.1 파싱 (원본 -> DXF -> CAIR 객체)

| 항목 | 내용 |
|---|---|
| 전수조사 | `python -m aec_intelligence.operational.cli census "<원본루트>" --out D:\AECData\census --resume` |
| 작업 등록 | `... enqueue-census D:\AECData\census [--only-folder ...] [--limit N] [--dry-run]` (sha256 기준 1회 적재, 사본은 aliases) |
| 처리 | `... run-workers -n <N> --out D:\AECData\census\runs` (DWG는 ODA 또는 LibreDWG로 DXF 변환) |
| 단건/개발 | `python -m aec_intelligence.cli ingest-dxf <파일> --project-id <ID> --name <이름>` (`packages/aec`) |
| 게이트 | 가용 RAM >= 2048MB에서만 라운드 시작, **workers=1 유지**. 증설은 RAM/DB 안정성/원본 접근 게이트를 통과한 뒤 1시간 관찰을 거쳐서만 |
| 전제 | 원본 경로가 마운트돼 있을 것. `G:`는 오늘 해제돼 있다가 사용자가 다시 마운트했음. 해제 중 `FileNotFoundError`는 "파일 없음"이 아니라 "접근 불가"로 분류 |
| 증거 파일 | `census.jsonl`/`census.csv`/`summary.md`, 워커 로그, `report.md`/`report.json`(census 대비 적재율) |

규칙:
- 원본은 불변. `AEC_IMPORT_ROOTS` 밖 경로는 건너뜁니다.
- 워커는 RAM 부족/원본 없음에서 죽지 않고 대기·재시도합니다(#38). 따라서 워커가 "Running"이어도 **실제 적재 진행의 증거가 아닙니다**. 진행은 `SUCCEEDED`와 `documents`의 증가로 확인합니다.
- `rclone` gdrive 토큰은 만료 상태입니다. 재연결은 **계정 소유자**가 합니다(에이전트는 자격증명을 입력하지 않음).

### 2.2 분석 (분류, 표제란, 객체 의미)

| 항목 | 내용 |
|---|---|
| 코드 | `packages/aec`의 `parsers.py`(표제란/도면번호), `classifier.py`(도면 분류). PR #51 참조 |
| 평가 | `independent_neutral_eval.py`(파일명 중립 20건), `packages/aec/scripts/eval_*.py` |
| 게이트 | **파일명 중립** 평가의 존재 적중만 인용. 새 규칙은 회귀 테스트 필수(`tests/test_title_block_text_number.py`) |
| 증거 파일 | 평가 JSON/로그, pytest 결과(CI) |

### 2.3 지침/메모리 (에이전트 컨텍스트)

| 항목 | 내용 |
|---|---|
| 명령 | `python -m aec_intelligence.cli memory`(프로젝트/전역 컨텍스트 재생성), `rebuild-global`, `refresh-derived` |
| 위치 | `packages/aec/global/09_AGENT_MEMORY/*.jsonl`(CAIR에서 재생성되는 파생물) |
| 사람이 쓰는 메모 | [`docs/agent-memory/drawing-ontology.md`](../agent-memory/drawing-ontology.md): 날짜가 붙은 짧은 사실 |
| 규칙 | `09_AGENT_MEMORY`는 손으로 고치지 않습니다. 사실 메모는 위 마크다운에 날짜와 함께 추가 |

### 2.4 DB (PostgreSQL + AGE + pgvector)

| 항목 | 내용 |
|---|---|
| 상태 확인 | `docker ps --format "{{.Names}} {{.Status}}"`, `docker exec aec-db psql -U aec -d aec -c "select state, count(*) from aec.jobs group by 1"`. API 헬스는 `/healthz`(`/health` 아님) |
| 쓰기 | 마이그레이션 `docker compose run --rm --no-deps migrate`(멱등). 라이브 DB 파일을 Drive 등으로 복사 금지 |
| 게이트 | 배포/재시작 전 `scripts\ops\stop-workers.ps1 -Drain`, 후 `-Resume` |
| 증거 파일 | `D:\AECData\dev\speedup-log.md`, `completion-matrix.md`, `PROGRESS.md` |

### 2.5 검증 (백업, 복구, 정확도)

| 항목 | 내용 |
|---|---|
| 백업 | `scripts\ops\backup.ps1 -Target D:\AECData\backups -Keep 7` |
| 복구 훈련 | `scripts\ops\restore-drill.ps1 -Dump <덤프>`. **격리 DB에서만**, 라이브 DB 복원 금지 |
| 증거 파일 | `checkpoint-recovery-receipt.json`, `restore-repair-report.json`, `completion-matrix.md` |
| 헤드리스 CI | "계약이 잘못된/모순된 증거를 거부하는가"만 증명합니다. 네이티브 CAD 검증이 아닙니다 |

---

## 3. 에이전트가 질의하는 방법

순서: **읽기 전용 질의 -> 근거 인용 -> 필요 시 열린 CAD에서 재확인**. 쓰기는 이 문서의 범위가 아닙니다.

### 3.1 power-cad `ontology_*` 도구 (읽기 전용)

설정: `POWERCAD_ONTOLOGY_URL`(Python 기본 `http://127.0.0.1:58000`, C# 서버는 필수), `POWERCAD_ONTOLOGY_TOKEN`
(서버의 `AEC_API_TOKEN`과 같은 값). 미설정이면 `[ONTOLOGY_NOT_CONFIGURED]`. 서비스가 꺼져 있으면 작도 도구는 영향이 없고 질의만 실패합니다.

| 목적 | 도구 |
|---|---|
| 무엇이 적재돼 있나(종류별 수, 도면 분류, 레이어, 층, 프로젝트) | `ontology_catalog` (**항상 먼저** 호출해 범위 확인) |
| 객체 찾기(문/창/벽 등, 레이어/블록/텍스트/bbox 필터) | `ontology_find_elements` |
| 도면 목록, 도면번호, 축척 | `ontology_drawings` |
| 블록 정의/사용 | `ontology_blocks`, `ontology_block_candidates` |
| 객체 주변 관계 | `ontology_element_context` (1-2 hop) |
| 하이브리드 검색 | `ontology_search` |
| 자연어 질의응답 + 인용 | `ontology_ask` (`refused:true`면 "근거 없음"으로 보고) |
| 작업 문장으로 묶음 조회 | `ontology_auto_context` |
| 열린 도면의 실제 handle | `ontology_locate` (**handle은 도면 하나 안에서만 고유**. 다른 도면의 handle을 `cad_*`에 넘기지 않음) |

### 3.2 Sion `GET /api/v1/aec/query` (읽기 전용 페더레이션)

- 요청: `GET /api/v1/aec/query?question=...&top_k=...&project_id=...`, `Authorization: Bearer ...`(스코프 `read:aec`). `question` 1-2000자.
- 응답: `{"source":"khs0927/Ontology","canonical":false,"read_only":true,"result":{...}}`. 클라이언트는 `canonical`이 JSON 불리언 `false`, `read_only`가 `true`가 아니면 거부합니다(`[SION_CONTRACT]`).
- 503 = 페더레이션 미구성, 502 = CAIR 오류. 둘 다 "도면에 없음"이 아니라 "조회 실패"로 보고합니다.
- 계약: [`docs/INTEGRATION_CONTRACTS.md`](../INTEGRATION_CONTRACTS.md) 2절.

### 3.3 답변 작성 형식

1. 사용한 도구와 질의(필터 포함), 조회 시각.
2. 결과 + 인용(문서/시트/객체 id). 인용 없는 수치는 쓰지 않음.
3. **범위 문구**: "적재된 674건 중"처럼 모집단을 밝히고 전체로 일반화하지 않음.
4. 신뢰도 등급(4.3절).

---

## 4. 신뢰도 규칙

### 4.1 금지

- **파일명 기반 평가로 정확도를 주장하지 않는다.** 번호·분류가 파일명에서 나왔다면 자기일치입니다.
  파일명 중립(해시화) 평가의 *존재 적중*만 인용하고, 정밀도/정확도/독립 전문가 평가라고 부르지 않습니다.
- 자기보고치나 그래프 자체 키(`kg:`)로 만든 gold를 독립 정확도로 인용하지 않는다.
  선례: "98.9%"는 pr1 94/95에서만 재현되고 master는 80/95(84.21%), 95셀 중 60셀은 독립 키가 없었음. "근거율 97.8%"는 44/45(답변가능)이며 분모를 50으로 하면 88.0%.
- 에이전트 검토 gold를 "전문가 검토 완료"로 쓰지 않는다.
- 작업 수, 문서 수, KG Drawing 수를 서로 바꿔 쓰지 않는다. "546건 적재"는 실제로 KG Drawing 노드 수였습니다.

### 4.2 백업/복구 용어 (섞어 쓰지 않음)

| 용어 | 의미 | 현재 |
|---|---|---|
| `BACKUP_VERIFIED` | 덤프 생성과 클라우드 readback 확인. **복원 가능성은 증명하지 않음** | 2026-10-08 덤프 2건(1.65GB): 미검증 |
| `RECOVERY_VERIFIED` | 격리 DB에 복원해 행/인덱스/쿼리를 원본과 대조해 일치 확인 | 2026-10-05 덤프, SHA256 `7c0228ab7e965f94a6720f1dfd52221c1d473d08b52189c2906abdc23f7b581b` (888 테이블 / 3,968,576 행 / 1,357 인덱스 일치, 복원 보고서 MATCH) |

- "최신 백업이 복구 검증됨"이라고 쓰려면 **그 덤프의 SHA256에 대한** 복원 보고서가 있어야 합니다. 10-05 검증은 10-08 덤프로 승계되지 않습니다.
- 복구 훈련은 격리 DB에서만. 라이브 DB 복원 금지.

### 4.3 결과 등급 (답변에 표기)

| 등급 | 조건 | 표현 예 |
|---|---|---|
| A. 적재 근거 있음 | 온톨로지/Sion 응답에 객체 id, 시트 인용 | "적재된 문서 X의 시트 Y에서 확인(객체 id ...)" |
| B. 추정 | 파서 점수 규칙(표제란 텍스트 번호) 또는 분류기 결과 | "표제란 텍스트 기반 추정, 독립 검증 없음" |
| C. 미적재/미확인 | 큐에 있거나 조회 실패 | "아직 적재 전이라 판단 불가" |
| D. 네이티브 미검증 | 호스트 CAD 동작, 정본 상태 | `UNVERIFIED_NATIVE`: 열린 CAD에서 `cad_*`로 재확인 |

CI 통과, 픽스처 통과, 헤드리스 계약 통과는 **네이티브 CAD 검증이 아닙니다**.

### 4.4 수치 인용 규칙

- 큐/문서 수는 쓰기 직전에 DB에서 다시 조회하고 **조회 시각을 함께 적는다**. 옛 스냅샷(예: 10-05의 QUEUED 21,840 / documents 549)을 현재 값으로 재사용하지 않는다.
- 처리 속도(건/h)는 오염 없는 동일 시간창의 append-only 이벤트로만. 과거 "27건/h"는 철회됐고 당시 실측 6시간 평균은 약 13건/h였습니다.
- 워커 "Running", API "health ok"는 진행/건강의 증거가 아니라 관찰 시점의 상태일 뿐입니다.

---

## 5. 표제란 도면번호 추출 규칙과 알려진 위험 (PR #51)

### 5.1 규칙 (PR #51 `feat/drawing-number-extraction` 기준)

> PR #51이 병합되기 전에는 main에 구현돼 있지 않을 수 있습니다. 인용 전에 코드를 확인합니다.

채움 순서: **TitleBlock INSERT 속성(`DWG_NO` 등) -> 표제란 TEXT/MTEXT -> 레이아웃명 -> 파일명**. 파일명은 마지막 폴백입니다.

표제란 TEXT/MTEXT 채택 절차:
1. 후보: 텍스트 **전체**가 도면번호 형식인 TEXT/MTEXT(`A-101`, `AR-1001`, `A-101-1`, `건축-01`, 공백 낀 대시 `C - 010`). 라벨 동일 텍스트(`DWG NO. A-101`)도 처리.
2. 점수: `도면번호/도번/DWG NO/SHEET NO` 라벨 근접 +4, 시트/표제 레이어 +2, 대시 표기 +1. **합계 3 이상만 채택**.
3. 최상위 후보가 4개를 넘으면(`MAX_SHEET_NUMBER_CANDIDATES`) **번호 없음**(도면목록 표 오탐 방지, 임의 1개 채택 금지).
4. 일반 레이어의 문/창 마크(`SD-01` 등)는 채택하지 않음.
5. 채택 시 `drawingNumber_source=title_block_text`. 에이전트는 이 출처값을 답변에 함께 적습니다.

분류 순서: `시방서`와 `확대 평면` 규칙은 상세도 앞, `구조도`는 최종 평면도 앞. `일람표`/`표지·목록`/창호/상세의 기존 우선순위를 유지합니다(리뷰에서 회귀를 발견해 수정).

### 5.2 평가 결과의 해석

- 파일명 중립 20건(origin/main 대비 동일 하네스): 도면번호 **0/14 -> 12/14**, 분류 14/18 -> 18/18, 층 8/9 -> 9/9.
- 이는 **존재 적중**이며 값이 맞는지의 정밀도가 아닙니다. gold는 에이전트 검토이고 전문가 검토 전입니다.
- 작성자 PC의 RAM 사정으로 하네스 RAM 게이트를 2048 -> 1024MB로 낮춰 실행했고, 리뷰의 분류 순서 수정 뒤에는 **재실행하지 않았습니다**(재확인 권장).
- 남은 2건은 다른 시트 번호를 선택했습니다(S-002 vs S-001, A-201 vs A-204). 목록/참조 번호 혼동으로 추정.

### 5.3 알려진 위험 (PR #51 독립 리뷰)

| 위험 | 에이전트 대응 |
|---|---|
| 시트 레이어(`TITLE\|도면\|출력\|FRAME` 등 넓은 패턴)와 대시 형태만으로 3점이 돼, 문서 번호나 상세 참조 버블(`A-501`)이 채택될 수 있음 | `title_block_text` 출처는 등급 B(추정)로 표기. 중요한 판단은 시트 자체로 확인 |
| `확대[^상]*평면`이 "계단 확대 단면도 및 평면도"를 평면도로 분류(모호) | 확대/복합 제목의 분류는 단정하지 않음 |
| 후보 x 라벨 O(N*M) 거리 계산: 라벨이 매우 많은 대형 DXF에서 비용 가능 | 대형 파일 지연 시 파서 병목을 의심 |
| 한글 정규화가 대문자화/공백 허용만 수행, 전각 대시(－, –) 미처리 | 전각 대시 도면은 번호 누락 가능. "번호 없음"은 "번호가 없다"가 아님 |
| `test_dwg.py::test_oda_converter_tolerates_undecodable_console_output`는 origin/main에서도 실패(PR과 무관) | 해당 실패를 이 변경 탓으로 돌리지 않음 |
| 평가 표본이 20건 | 일반화 금지 |

번호가 비어 있는 결과는 **추출 실패**로 취급하고 파일명에서 지어내지 않습니다. 파일명 폴백 결과는 출처를 `filename`으로 표기합니다.

---

## 6. 근거 파일 위치

| 파일 | 내용 |
|---|---|
| `docs/STATUS.ko.md` | 모노레포 상태, 오너 할 일 |
| `packages/aec/docs/verification-boundary.md` | 헤드리스 vs 네이티브 검증 경계 |
| `D:\AECData\dev\completion-matrix.md` | 가속 계획 A-H 완료 증거 행렬(10-05 기준, 현재 수치 아님) |
| `D:\AECData\waves\FINDINGS.md` | Wave 1-2 독립 감사 |
| `docs/INTEGRATION_CONTRACTS.md` | power-cad <-> Sion 계약 |
| PR #51 본문과 리뷰 코멘트 | 도면번호 추출, 리뷰 발견 |
| power-cad `README.md` Ontology 절 | `ontology_*` 도구 표, 환경변수 |

## 7. 오너가 해야 하는 일 (에이전트가 대신하지 않음)

- `rclone` gdrive 토큰 재연결(만료).
- 2026-10-08 덤프 2건(1.65GB)의 격리 복원 검증 실행 승인.
- `G:` 마운트 유지(해제되면 적재가 `FileNotFoundError`로 쌓임).
- 전문가가 검토한 독립 gold를 확보하기 전까지 정확도 수치를 공식 문서/보고에 쓰지 않기.
