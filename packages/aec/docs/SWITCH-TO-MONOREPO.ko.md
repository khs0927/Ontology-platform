# 운영 PC 전환 런북: 보관된 Ontology 체크아웃 → Sion 모노레포 `packages/aec`

khs0927/Ontology 저장소가 보관(읽기 전용)되고 코드가 Ontology-platform 의 `packages/aec` 로 들어왔습니다.
운영 PC 에서는 아직 예전 체크아웃(예: `C:\CODE\Ontology`)을 기준으로 다음이 돌고 있습니다.

- docker compose `aec-db`(127.0.0.1:55432), `aec-api`(127.0.0.1:58000), `.env`(AEC_API_TOKEN 포함)
- 호스트 venv `.venv` (ODA 변환·OCR·적재 워커)
- 예약작업 `\AEC\`: AEC-Bulk-Workers, AEC-Bulk-Census, AEC-Bulk-Census-Refresh, AEC-Ollama, AEC-Reembed,
  AEC-WSL-Reclaim, AEC-GraphRAG-Refresh, 일회성 AEC-Ops-FinalWrap / AEC-Ops-FinalCheck

`scripts/ops/switch-to-monorepo.ps1` 하나로 이것들을 모노레포 기준으로 옮깁니다. **기본은 드라이런**이고
`-Apply` 를 붙여야 실제로 바뀝니다.

## 1. 준비 (5분)

```powershell
# 모노레포 체크아웃 (예: $env:USERPROFILE\CODE 아래, Google Drive 동기화 폴더는 피하세요)
git clone https://github.com/khs0927/Ontology-platform.git "$env:USERPROFILE\CODE\Ontology-platform"
cd "$env:USERPROFILE\CODE\Ontology-platform"
git switch main; git pull
```

- 작업 트리가 깨끗해야 하고 브랜치가 `main` 이어야 합니다(아니면 스크립트가 멈춥니다).
- Docker Desktop 이 켜져 있어야 합니다.

## 2. 드라이런 (변경 없음)

```powershell
powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot C:\CODE\Ontology
```

확인할 것:
- `compose project=... db volume=<project>_aec-pgdata` — 지금 `aec-db` 가 쓰는 볼륨과 같아야 합니다.
  (`docker inspect aec-db` 의 compose 라벨과 마운트에서 자동 감지. 다르면 스크립트가 거부합니다.)
- `task \AEC\... legacy=True` 목록 — 전환 대상
- `AutoSync_Code_To_GDrive` 상태
- `host venv interpreter: ... (Python 3.12 이상)` — 모노레포 루트가 Python 3.12+ 를 요구하므로, 예전 venv 가
  3.11 이면 `py -3.13`/`py -3.12` 또는 PATH 의 3.12+ 를 고릅니다. 찾지 못하면 **아무것도 바꾸기 전에** 멈춥니다
  (`-Python <python.exe 경로>` 로 직접 지정 가능, 3.12 미만이면 거부).
- 마지막 줄의 `[DRY-RUN] would ...` 계획

## 3. 실행

```powershell
powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot C:\CODE\Ontology -Apply
```

순서: 작업 XML 백업 → 워커 드레인(`stop-workers.ps1 -Drain`, 돌던 작업은 끝까지 처리) → `\AEC\` 작업 일시
비활성화(AEC-Ollama 제외) → pg_dump 안전 백업(`backup.ps1`) → `.env` 복사(값은 출력하지 않음,
`COMPOSE_PROJECT_NAME` 고정) → `docker compose -p <project>` build api / up db / run migrate / up api →
`packages\aec\.venv` 재생성(`pip install -e ".[operational,pdf,bim,ocr,cad]"` + 모노레포 루트 `--no-deps`) →
`register-bulk-tasks.ps1`·`register-host-tasks.ps1` 로 작업 재등록 → FinalWrap/FinalCheck 삭제 →
`\AEC\` 작업 재활성화(단, 여전히 `-LegacyRoot` 를 가리키는 작업은 **비활성 상태로 남기고** WARN — 직접 옮긴 뒤 켜세요) →
`AutoSync_Code_To_GDrive` 비활성 확인 → `/healthz`, `/v1/kg/stats` 확인 → `AEC-GraphRAG-Refresh` 시작(재색인) →
`stop-workers.ps1 -Resume`.

### 데이터가 안전한 이유
- compose 는 볼륨 이름을 `<프로젝트명>_aec-pgdata` 로 만듭니다. 폴더 이름이 `Ontology` → `aec` 로 바뀌면
  기본 프로젝트명도 바뀌어 **빈 DB 가 새로 초기화**됩니다. 스크립트는 기존 프로젝트명을 감지해
  `-p` 와 `.env` 의 `COMPOSE_PROJECT_NAME` 으로 고정하고, 전환 후 `aec-db` 가 같은 볼륨을 쓰는지 다시 검사합니다.
- `migrate` 는 `init-db`(이미 적용된 마이그레이션은 건너뜀)라 기존 데이터를 지우지 않습니다.
- 전환 직전 pg_dump 를 한 번 더 남깁니다(`-SkipBackup` 으로 생략 가능).

### 자주 쓰는 옵션
| 옵션 | 뜻 |
|---|---|
| `-OllamaHome <경로>` | register-host-tasks.ps1 에 그대로 전달 (기본 `C:\AECLocal\Ollama`) |
| `-Config <sources.json>` / `-Workers 2` | register-bulk-tasks.ps1 에 전달 |
| `-ComposeProject <이름>` | 자동 감지 대신 지정 (aec-db 라벨과 다르면 거부) |
| `-DrainTimeoutMin 30` | 긴 DWG/PDF 작업 대기 시간 |
| `-SkipCompose` `-SkipVenv` `-SkipGraphRag` `-SkipBackup` `-NoResume` | 단계별 생략 (재실행 시 유용) |

## 4. 결과 확인

- 로그: `D:\AECData\bulk\logs\switch-to-monorepo-<시각>.log` (`AEC_DATA_ROOT` 기준)
- 백업: `D:\AECData\switch-backup\<시각>\` — 작업 XML, `legacy-pip-freeze.txt`
- `Get-ScheduledTask -TaskPath '\AEC\' | ft TaskName, State` — 모든 작업 Ready/Running, 경로가 `packages\aec`
- `powershell -File packages\aec\scripts\ops\graphrag.ps1 stats` — KG 통계
- `warning(s)` 가 0 이 아니면 로그의 WARN 줄을 확인하세요.

## 5. 문제 생겼을 때 (롤백)

예전 체크아웃은 전혀 건드리지 않습니다. 작업만 되돌리면 됩니다.

```powershell
$b = 'D:\AECData\switch-backup\<시각>'
Get-ChildItem $b -Filter 'AEC_*.xml' | ForEach-Object {
  $name = $_.BaseName -replace '^AEC_', ''
  Register-ScheduledTask -TaskPath '\AEC\' -TaskName $name -Xml (Get-Content $_.FullName -Raw) -Force
}
cd C:\CODE\Ontology; docker compose up -d db api   # 같은 프로젝트·볼륨이므로 데이터 그대로
powershell -ExecutionPolicy Bypass -File scripts\ops\stop-workers.ps1 -Resume
```

- 드레인이 시간 안에 안 끝나면(긴 작업) 스크립트는 아무것도 바꾸지 않고 멈춥니다. 같은 명령을 다시 실행하세요.
  그만두려면 `stop-workers.ps1 -Resume` 으로 정지 파일을 지웁니다.
- 중간 단계에서 실패하면 `\AEC\` 작업이 비활성 상태로 남을 수 있습니다. 원인을 고친 뒤 같은 명령을 다시
  실행하거나(이미 끝난 단계는 `-Skip*` 로 생략), 위 롤백을 하세요.

## 6. 전환 후 할 일
- `/review` 화면에서 관계 후보 승인/반려 (사람 판단 필요)
- 며칠 안정적으로 돈 뒤 예전 `.venv`(`packages\aec\.venv.old-*` 포함)와 예전 체크아웃 정리는 직접 결정하세요.
  `.venv.old-*` 와 복사된 `docker-compose.override.yml` 은 git 에서 무시되므로, 중간에 실패해도 깨끗한 작업 트리
  검사에 걸리지 않고 그대로 다시 실행할 수 있습니다.
  스크립트는 아무것도 지우지 않습니다.
