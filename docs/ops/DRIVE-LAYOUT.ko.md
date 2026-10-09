# Google Drive 레이아웃 가이드 (DRIVE-LAYOUT)

작성일: 2026-10-09. 근거 문서: `docs/STORAGE.md`, `docs/SYNC_ARCHITECTURE.md`, `README.md`.
상태: 가이드 초안. 실제 Drive 내용 감사는 아직 수행되지 않음 (아래 "감사 상태" 참고).

## 0. 감사 상태 (2026-10-09 재개 후)

- `G:\내 드라이브` 는 재마운트 후 읽기 가능했으나 감사 도중 `G:` 가 다시 사라졌다(DriveFS 마운트 불안정). 따라서 **이동 0건 / 삭제 0건**, 매니페스트/undo 스크립트 없음.
- 인벤토리(읽기 전용): My Drive 루트에 약 60개 폴더 + 약 150개 개인/잡다한 파일(.gdoc/.gsheet, zip, 이미지 등)이 섞여 있다. AEC 관련 정본은 `AEC-INTELLIGENCE\` 하나이고 크기는 약 2.6GB.
  - 90_ARCHIVE 2.49GB(전부 db-checkpoints, 파일 12개), 01_PROJECTS 0.12GB(230개), 나머지 번호 폴더는 합계 수 MB. 04_CAIR, 05_ARTIFACT_REGISTRY, 06_CLASSIFICATIONS 는 비어 있음.
  - 01_PROJECTS 아래: SION-ONTOLOGY(118MB), AEC-2026-000001/000003/000004 샘플 프로젝트.
  - SION-ONTOLOGY 안에는 00_SOURCES, 01_SNAPSHOTS, 02_EXPORTS, 03_DOCS, 09_AGENT_MEMORY, `09_RECOVERY`(문서화된 레이아웃에 없음), storage-manifest.json, cleanup-2026-10-08.log 가 있다.
- 취급 금지: `##작업중`, `1.회사` 는 수집(ingestion) 소스이므로 내부 이동 금지. 이외 루트 개인 폴더는 소유자 영역이라 건드리지 않는다.

### Drive 측 DB 체크포인트 (90_ARCHIVE\db-checkpoints) 비교

| package | Drive 크기 | Drive SHA256 | 로컬 영수증/사본과 비교 |
| --- | --- | --- | --- |
| b20f9160... | 764,976,533 | 7c0228ab...b581b | 일치 (RECOVERY_VERIFIED). Drive 에 restore-report.json 포함 |
| 410d25e2... | 753,033,819 | 0aad9937...12610 | 일치 (BACKUP_VERIFIED, 복원 미검증). PROVENANCE-CORRECTION.txt 포함 |
| 8c405d66... | 1,153,838,125 | 읽기 중 G: 해제로 미검증 | 크기 일치. 로컬 사본 SHA256 D6D1F879...A41C8 (= 로컬 aec-db-20261004T094218Z.dump). 영수증/복원 보고서 없음 → 미검증 |

- `backups\aec-db-20261008T190226Z.dump.partial` (24.6MB)은 업로드가 진행 중인 파일이므로 건드리지 않는다.
- 로컬 `D:\AECData\backups` 의 2026-10-08 덤프 2개(1,652,469,511B; SHA256 61EB15A5..., 94E11A66...)와 20261005T193005Z, 20261006T193326Z 는 Drive 체크포인트나 영수증이 없다 → 미게시/미검증.

## 1. 정본 폴더 레이아웃

```
<My Drive>\
  .CODE\_sync-v2\
    devices\<device-id>\workspaces\C_CODE\...   PC별 자동 안전 복사본 (덮어쓰기 대상, 사람이 편집 금지)
    canonical\<project>\<git-sha>\...           검증된 릴리스 스냅샷 (불변, 추가만)
  AEC-INTELLIGENCE\
    01_PROJECTS\SION-ONTOLOGY\                  = SION_STORAGE_ROOT
      00_SOURCES\      원본 자료, sha256 콘텐츠 주소 저장소 (objects\sha256\..)
      01_SNAPSHOTS\db\ sion-<UTC>.db|.dump, sion-latest.* (최신 20개 유지)
      02_EXPORTS\      graph\, bootstrap\, agent-bridge\
      03_DOCS\         지식 문서
      09_AGENT_MEMORY\ 에이전트 메모리 내보내기
      storage-manifest.json
    03_KNOWLEDGE_GRAPH\   정제된 지식 그래프 산출물 (JSONL/JSON-LD/GraphML/Parquet)
    09_AGENT_MEMORY\      에이전트 메모리 (프로젝트 공통)
    10_EXPORTS\           외부 전달용 내보내기
    90_ARCHIVE\db-checkpoints\<package_id>\  DB 체크포인트 (database.dump, manifest.json, restore-report.json)
    _ops\                 정리/감사 기록 (reorg-manifest-<date>.csv, undo-*.ps1)
```

## 2. 무엇을 어디에

| 대상 | 위치 |
| --- | --- |
| 원본 SketchUp/CAD/PDF 등 수집 자료 | `01_PROJECTS\SION-ONTOLOGY\00_SOURCES\` |
| DB 스냅샷 (SQLite/pg_dump) | `01_SNAPSHOTS\db\` (신규 운영 체크포인트는 `90_ARCHIVE\db-checkpoints\`) |
| 그래프/증거 내보내기 | `02_EXPORTS\graph\` |
| 규칙/지침 문서 | `03_DOCS\` |
| 에이전트 메모리 | `09_AGENT_MEMORY\` |
| 코드 | Git/GitHub 이 정본. Drive 는 `.CODE\_sync-v2` 안전 복사본만 |
| 임시/실험 파일 | Drive 에 두지 않음 (로컬 `D:\AECData\...`) |

## 3. 이름 규칙

- 타임스탬프는 UTC `YYYYMMDDTHHMMSSZ` (예: `aec-db-20261008T133440Z.dump`).
- 최신 포인터는 `*-latest.*`, 이력은 타임스탬프 파일. 포인터만 덮어쓴다.
- 체크포인트 폴더 이름은 `package_id`(32 hex), 안에 `manifest.json`(sha256, bytes, status)을 반드시 둔다.
- `.partial`, `~$*`, `*conflict*`, `(1)` 접미 파일은 정본이 아니다. 보관하지 말고 소유자가 확인 후 정리한다.
- 공백/한글은 폴더명에 허용하지만 파일명은 ASCII 를 권장한다.

## 4. 백업/검증 규칙

- **BACKUP_VERIFIED**: 덤프를 Drive 에 올리고 원격 읽기(cloud read-back) 체크섬이 일치함. 복원 가능성은 증명하지 않는다.
- **RECOVERY_VERIFIED**: 격리된 scratch DB 에 실제 복원 후 테이블/행/인덱스/핵심 쿼리가 모두 MATCH (예: `restore-repair-report.json`, result=MATCH). 해당 dump 의 SHA256 에 연결된 보고서가 있어야 한다.
- BACKUP_VERIFIED 를 RECOVERY_VERIFIED 로 승격하지 않는다. 복원 훈련은 라이브 DB 에 하지 않는다.
- 모든 체크포인트는 manifest 에 sha256/bytes 를 기록하고, 업로드 후 read-back 으로 재검증한다. `source_commit` 이 불명이면 불명이라고 기록한다.
- 보관: `sion-<UTC>` 최근 20개, 체크포인트는 삭제하지 않고 `90_ARCHIVE` 에 누적. 삭제는 소유자 승인 후에만.
- 정리(이동) 시 `_ops\reorg-manifest-<date>.csv`(src,dst,size,sha256(<200MB),time)와 undo `.ps1` 을 반드시 남긴다. 삭제는 하지 않는다.

## 5. 절대 동기화하면 안 되는 것

- 라이브 DB: PostgreSQL 데이터 디렉터리, SQLite `*.db` + `-wal`/`-shm`/`-journal`, Docker/WSL 볼륨 이미지.
- 실행 중 프로세스가 쓰는 폴더 (API `runtime\`, pg 데이터, 임베딩 캐시, ollama/hf 캐시).
- `.env`, 키, 토큰, `userkey.psw`, NPKI 인증서.
- `node_modules`, `.venv`, 빌드 산출물, 컨테이너 레이어.
- 라이브 DB 는 로컬 디스크(`D:\AECData` 등)에 두고, Drive 에는 논리 덤프/스냅샷만 export-on-write 로 보낸다. `C:\CODE` 가 DriveFS 백업 대상이므로 이 아래에 DB 파일을 두지 않는다.

## 6. 현재 알려진 DB 체크포인트 (로컬 영수증 기준)

| package_id | 상태 | SHA256 | 크기 |
| --- | --- | --- | --- |
| b20f916059204ba9989be57ee72db766 | RECOVERY_VERIFIED, read-back true | 7c0228ab7e96...b581b | 764,976,533 |
| 410d25e22a9d473d9dfc72558ca35471 | BACKUP_VERIFIED (복원 미검증) | 0aad99373673...12610 | 753,033,819 |

로컬 사본 D:\AECData\checkpoint-staging\ 의 해시가 영수증과 일치함을 2026-10-09 에 재확인했다.
원격(`gdrive:AEC-INTELLIGENCE/90_ARCHIVE/db-checkpoints/`) 존재 여부는 인증 만료로 이번에 재확인하지 못했다.

## 7. 소유자 확인 필요 (needs-owner)

- `G:` 마운트가 불안정하다(감사 중 두 번 해제). 안정화 후 이동 작업을 재개해야 한다.
- 루트의 AEC 관련 후보 폴더(`08_VALIDATION`, `PowerCad`, `PowerCad-Assets`, `SketchUp-Assets`, `Sion Ontology Artifacts`, `Ontology-platform-verification-2026-09-24`, `cokacmux-graph`, `지음_CAD_DB`, `GrokBot-Migration-2026-10-08`, `hillside_villa_export`, `revit-mcp-guideline`)와 루트의 `Ontology_*_2026100x.zip`, `Claude_Drive_처리_인계_20261002.md`, `hillside_villa.rvt` 는 `AEC-INTELLIGENCE` 하위로 옮길 후보지만, 참조 여부가 불확실하여 이동하지 않았다.
- `AEC-INTELLIGENCE\08_VALIDATION` 과 루트 `08_VALIDATION` 중복 여부, `SION-ONTOLOGY\09_RECOVERY` 의 용도.
- 루트에 `GoogleDrive-<계정> (2026. 7. 15...)`, `새 폴더`, `무제 폴더`, `Untitled`, `제목 없는 *` 등 임시/중복 성격 항목이 있음 (삭제 금지, 소유자 판단).
- `my_key.key`, `encrypted_data.bin`, `NPKI`, `GPKI` 가 Drive 루트에 있음 (비밀 정보, 5절 위반 가능성).
- 체크포인트 8c405d66 의 Drive 해시 검증, `.dump.partial` 처리, 로컬 최신 덤프 4종의 게시/복원 검증.
- `rclone config reconnect gdrive:` (토큰 만료).
