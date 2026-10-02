# 전체 Drive 도면 적재 실행 상태 — 2026-10-02 KST

## 완료
- 사용자 지시에 따라 Ontology PR #15를 ready 상태로 전환한 뒤 head 142f48f94ef84102944ffbee3327c1b88db253e8을 expected_head_sha로 고정해 merge했다.
- merge commit: b232594bfb391af2853d7b8b31e4a4e741526234.
- 병합 후 master CI success: https://github.com/khs0927/Ontology/actions/runs/36999831269 .
- Google Drive 연결에서 도면 폴더 검색 및 도면(프로젝트별) 하위 항목 조회 성공. 원본은 변경하지 않았다. 전체 파일 수 34,000여 개는 사용자/Claude 전달 수치이며 이 세션에서 전수 재계수한 값이 아니다.

## 현재 실행 상태
FULL_INGESTION_NOT_STARTED_BY_THIS_SESSION. 다른 Claude 스레드의 작업/PC 프로세스를 볼 수 없어 다른 세션에서의 시작 여부는 미확인이다.
- Desktop Commander: 등록된 DESKTOP-KTQHS1I offline.
- remote 회사컴퓨터: read-only stat 호출이 reauthentication required로 실패.
- remote 집컴퓨터(안방): read-only stat 호출이 internal error로 실패.
- Activepieces 현재 프로젝트에서 이름 ontology로 검색한 flow 0개. 다른 이름의 flow 부재를 뜻하지 않는다.
- 이 상태에서 PC·DB·기존 worker·Drive mount를 확인할 수 없으므로 중복 worker를 시작하지 않았다.
- 다른 Claude 스레드의 원격 실행 카드 승인 상태는 이 ChatGPT에서 변경하지 못했다.

## 기존 병합 코드에 반영된 경로
- 기본: Drive for Desktop에 마운트된 원본 -> census --resume -> SHA-256 중복 제거/alias -> enqueue-census -> PostgreSQL worker -> graph/object/embedding -> report.
- DWG: ODA 우선, 없으면 LibreDWG dwg2dxf. DXF는 직접 파싱. PDF는 제목란/치수/그리드/벽 후보와 텍스트 없는 페이지 경고.
- 긴 한글 경로 대응, converter 출력 decoding, Space/SteelSection과 공간 관계, 자동 worker 개수, 선택적 bge-m3 embedding, reembed 명령 포함.
- 서비스 계정은 키만 등록해도 기존 PC 실행이 자동 대체되는 것으로 간주하지 않는다. 실제 대량 binary download/staging과 지속 DB/worker 실행환경, Drive 파일 접근 권한을 함께 검증해야 한다. 키를 GitHub 코드/문서/대화에 기록하지 않는다.
- ChatGPT Drive 연결은 폴더 접근 성공을 확인했지만, 지속적인 34,000-file worker나 연결된 운영 DB를 제공하는 실행 경로로 확인된 것은 아니다.

## 재연결 후 단일 실행 담당자의 절차
1. 회사/집 중 실제 도면 mount와 운영 DB가 있는 PC를 확인한다. 인증이 필요한 연결은 재연결하고, 기존 Claude pipeline/worker/process와 jobs 상태를 읽기 전용으로 조회한다.
2. 기존 checkout의 git status/HEAD를 확인한다. 미커밋 변경을 보존한다. 실행환경은 merge SHA를 별도 clone/worktree에서 준비하고 공유 checkout을 reset/clean하지 않는다.
3. 실제 mount root, AEC_DATA_ROOT, AEC_IMPORT_ROOTS, DB 연결, 저장 공간, converter 설치를 확인한다. 문서의 G:\내 드라이브는 예시이며 실제 PC 경로 확인 없이 실행하지 않는다.
4. 기존 pipeline이 실행 중이면 추가 전체 census/worker/reembed를 시작하지 말고 해당 run의 report/queue 진행을 관측한다.
5. 병합된 scripts/ops/run-pipeline.ps1에 검증된 root를 전달해 먼저 -PreflightOnly로 확인한다. 실패 시 -SkipPreflight로 우회하지 않는다.
6. 검증된 root에 -Limit 없이 실행하면 전체 enqueue 대상이다. -Workers 0은 CPU/RAM 기준 자동값이다. 첫 실행은 RAM/I/O/ODA 동시성 근거로 worker 수를 제한하고 처리율을 본 뒤 조정한다.
7. 임베딩 서버가 이미 준비되었거나 model download/메모리 여유가 있으면 -Embeddings를 사용한다. 그렇지 않으면 파싱·그래프를 우선 적재하고 뒤에 별도 reembed한다. hash vector를 semantic embedding 성공으로 기록하지 않는다.
8. 완료 판정은 census 대비 고유 원본/alias, QUEUED/RUNNING/DONE/FAILED, 오류 유형별 실패, 객체·관계·provenance, 실제 의미 검색 표본을 report로 확인한다. 중단은 기존 --resume/lease/dedup을 사용해 재개한다.
9. 기존 적재 변경 전에 운영 담당자의 백업과 동일 DB를 공유하는 다른 세션 실행 여부를 확인한다. 이 세션에서는 DB migration/reembed/backup/원본 이동을 실행하지 않았다.

## 실행 명령 템플릿 (실제 PC 검증 후)
```powershell
# 검증한 merge SHA의 작업 디렉터리에서, 실제 경로를 명시한다.
$verifiedDriveRoot = '<실제로 확인한 Drive 도면 루트>'
powershell -ExecutionPolicy Bypass -File scripts\ops\run-pipeline.ps1 -Root $verifiedDriveRoot -PreflightOnly
# 통과하고 기존 실행이 없을 때 전체 적재. 자동 worker 수, 전체 범위.
powershell -ExecutionPolicy Bypass -File scripts\ops\run-pipeline.ps1 -Root $verifiedDriveRoot -Workers 0
# bge-m3 서버 준비가 확인되면 위 전체 명령에 -Embeddings를 추가한다.
```

## 다음에 필요한 외부 조치
실제 데이터 PC의 원격 연결 재인증/온라인 전환 또는 사용자가 언급한 Claude Drive 스레드 카드의 PC 실행 허용이 필요하다. 현재 요청으로 전체 적재는 승인되었으므로 같은 작업 승인 질문을 반복할 필요는 없다. 실행 연결 복구와 실행 담당 PC 확인은 여전히 필요하다.
