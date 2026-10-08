# 메인 PC 복귀 시 할 일 (체크리스트)

작성: 2026-10-08 저녁, 1단계 갱신 22:00 (Asia/Seoul) · 대상: 메인 PC(운영 DB·API·대량 수집이 도는 PC)
실행 주체: 오너 또는 오너가 이 대화/세션에서 PC 제어를 허락한 에이전트.

> **규칙**
> - 위에서부터 **순서대로** 진행합니다. 앞 단계의 성공 기준을 못 맞추면 다음으로 넘어가지 않습니다.
> - 스크립트는 **드라이런 먼저**, 결과를 확인한 뒤 `-Apply`.
> - `.env`의 `AEC_API_TOKEN` 등 비밀값은 **절대 화면·로그·PR에 출력하지 않습니다**.
> - DB 볼륨(`<project>_aec-pgdata`)은 **재초기화·삭제 금지**. 작업 XML·설정 파일은 바꾸기 전에 백업합니다.
> - 관리자 권한이 필요한 단계는 오너가 직접 실행합니다(에이전트는 UAC를 우회하지 않음).
> - 경로 표기: `<USER_HOME>` = `$env:USERPROFILE`, `<LEGACY_ONTOLOGY>` = 보관된 Ontology 예전 체크아웃
>   (예: `C:\CODE\Ontology`), `<SION>` = Ontology-platform 작업 체크아웃.

진행 표시: 각 항목의 `[ ]`를 `[x]`로 바꾸고 시각을 적어 두면 다음 사람이 이어받기 쉽습니다.

---

## ★ 최우선 (메인 PC와 무관, 어느 PC에서든 바로)

- [ ] **HS-CAD에 커밋됐던 Google AI Studio API 키 교체(rotate)**
  - **왜:** HS-CAD의 `opencode.json`에 키가 들어간 채 2026-05-21부터 **공개 히스토리**에 남아 있습니다. 현재 main은
    HS-CAD #158 이후 `{env:GOOGLE_GENERATIVE_AI_API_KEY}` 환경변수를 읽지만, 히스토리의 옛 키는 이미 노출된 것으로 봐야 합니다.
  - **방법:** Google AI Studio의 API 키 화면에서 해당 키를 **삭제(폐기)** → 새 키 발급 → 쓰는 PC마다 사용자 환경변수
    `GOOGLE_GENERATIVE_AI_API_KEY` 로만 설정(파일·저장소·채팅에 붙여 넣지 않음).
    ```powershell
    [Environment]::SetEnvironmentVariable('GOOGLE_GENERATIVE_AI_API_KEY', (Read-Host -AsSecureString '새 키' | ConvertFrom-SecureString -AsPlainText), 'User')
    ```
  - **그다음:** HS-CAD 저장소 → Security → Secret scanning → **알림 #1** 을 "Revoked"로 닫기.
  - **성공 기준:** 옛 키로 호출하면 인증 실패, 새 키는 환경변수로만 동작, 알림 #1 닫힘.
  - **롤백:** 없음(폐기한 키는 되살리지 않음). 새 키에 문제가 있으면 새로 하나 더 발급.
- [ ] (선택) power-cad-mcp, hs-steel-cad, All-In-Cad 저장소에 **Dependabot alerts + Secret scanning** 켜기
  (Settings → Code security). 끄면 원래대로 돌아갑니다.

## ☆ HS-CAD PR 정리 — 오너 판단 (메인 PC와 무관)

PR 분류는 끝났습니다(2026-10-08 저녁). **32개 닫음**(내용이 이미 main에 있음), 병합 0개, **34개 열림**(각 PR에 한국어 코멘트로 판단 근거 기록).

- [ ] **(1) 분석 체인 2개 닫기 (−14개):** main이 아래 두 체인의 내용을 모두 포함하는지 확인한 뒤 닫습니다.
  - 체인 A: #23 #25 #27 #29 #32 #34 #35
  - 체인 B: #24 #26 #28 #30 #31 #33 #37
  - **확인:** 각 PR의 한국어 코멘트에 적힌 대응 파일이 main에 있는지 확인 → `gh pr close <번호> -R khs0927/HS-CAD -c "main에 포함되어 닫음"`.
  - **롤백:** 닫은 PR은 `gh pr reopen <번호>` 로 다시 열 수 있습니다.
- [ ] **(2) #1 #4 #5 #7:** 고유 모듈이 있지만 main과 충돌합니다. 그대로 병합하지 말고 **필요한 모듈만 main 기준 새 PR로 이식**
  (원래 PR은 이식 후 닫기).
- [ ] **(3) #12:** 작은 수정. 현재 `main.py` 기준으로 새로 작성(원래 PR은 닫기).
- [ ] **(4) 실기 실행:** ZWCAD 실행 검증이 필요한 PR은 **Windows + ZWCAD PC**에서만 확인 가능합니다(예: #146).
- [ ] **이전 라운드부터 열린 PR:** #66 #68 #69 #70 #71 #74 #76 #124 #126 #127 #146 #147 #154 #155 #156 — 각 코멘트를 보고 유지/닫기 결정.
- **주의:** xiCAD 쪽 `mcp==1.28.1` 고정은 **Python 3.13에서 설치가 깨집니다**. 3.12 venv를 쓰거나 고정 버전을 올리는 PR이 필요합니다.

## ☆ 기타 저장소 — 오너 판단 (메인 PC와 무관)

- [ ] **All-In-Cad:** 브랜치 `agent/autocad-host-2027`(`edba1f9`, PureWindowsPath 테스트 수정, dxf-recorder-ci 통과)은 아직 PR이 없습니다.
  올려서 병합할지 결정 → `gh pr create -R khs0927/All-In-Cad --head agent/autocad-host-2027 --base main` 후 CI 확인·병합.
  원치 않으면 브랜치를 그대로 두면 됩니다(삭제는 오너 확인 후).
- [ ] **zium-onboarding:** #1 병합(`bacdf61`, lockfile 재동기화·lint 오류 0) 후에도 **템플릿 테스트 실패 11개**가 남아 있습니다.
  새 브랜치에서 수정 PR → CI 초록 확인 후 병합.

## 0. 사전 점검 (2분)

- [ ] **왜:** 전환 중 Docker/WSL이 꺼져 있거나 디스크가 부족하면 중간에 멈춥니다.
- **명령**
  ```powershell
  docker version --format '{{.Server.Version}}'
  docker ps --format '{{.Names}} {{.Status}}' | Select-String 'aec-'
  Get-PSDrive C, D | Format-Table Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
  Get-ScheduledTask -TaskPath '\AEC\' | Format-Table TaskName, State
  ```
- **성공 기준:** Docker 서버 버전이 나오고 `aec-db`·`aec-api`가 `Up`. C:/D: 여유 10 GB 이상.
- **롤백:** 해당 없음(읽기 전용).

## 1. 모노레포 main 받기 (5분)

- [ ] **왜:** 운영 코드는 이제 `Ontology-platform`의 `packages/aec`가 기준입니다. 전환 스크립트는 깨끗한 `main`에서만 돕니다.
  2026-10-08 12:23 KST에 개인정보 정리용 히스토리 재작성(force push)이 있었습니다(그 전 03:11에 exe 제거 재작성도 있었음).
  그 전에 만든 체크아웃은 `origin/main`과 **갈라져** 있어서 `git pull --ff-only`가 실패합니다. 백업한 뒤 `origin/main`으로 맞춥니다.
- **명령** (작업 체크아웃은 `C:\code` 아래, Google Drive 동기화 폴더 **밖**)
  ```powershell
  $SION = 'C:\code\Ontology-platform'
  $BK   = "$env:USERPROFILE\sion-bundles"        # 저장소 밖 백업 폴더
  if (-not (Test-Path $SION)) {
    git clone https://github.com/khs0927/Ontology-platform.git $SION
  } else {
    git -C $SION status --short --branch            # 로컬 변경·현재 브랜치 확인
    git -C $SION fetch origin --prune
    git -C $SION merge-base --is-ancestor HEAD origin/main; "HEAD가 origin/main에 포함됨(0=예): $LASTEXITCODE"
    # 백업: 모든 로컬 ref 번들 + 커밋 안 한 변경 diff + 이전 HEAD 기록
    $ts  = Get-Date -Format yyyyMMdd-HHmmss
    New-Item -ItemType Directory -Force $BK | Out-Null
    $old = git -C $SION rev-parse HEAD
    $old | Set-Content "$BK\Ontology-platform-pre-reset-$ts.head.txt"
    git -C $SION bundle create "$BK\Ontology-platform-pre-reset-$ts.bundle" --all
    git -C $SION diff HEAD --binary --output="$BK\Ontology-platform-pre-reset-$ts.diff"
    git -C $SION bundle verify "$BK\Ontology-platform-pre-reset-$ts.bundle"
    # 백업 확인 후에만: main을 새 히스토리로 맞춤 (커밋 안 한 변경은 사라지고 백업 diff에만 남음.
    # 추적되지 않는 새 파일은 reset --hard가 지우지 않으므로 그대로 남음)
    git -C $SION switch -f main
    git -C $SION reset --hard origin/main
  }
  git -C $SION status --short --branch
  git -C $SION log --oneline -3
  git -C $SION merge-base --is-ancestor 54e1921 HEAD; "새 히스토리(0=예): $LASTEXITCODE"
  git -C $SION branch -vv                           # 예전 히스토리 기반 로컬 브랜치 확인 (푸시 금지)
  ```
- **성공 기준:** `## main...origin/main`, 변경 파일 없음, 최근 로그에 PR #48 이후 병합 커밋이 보임, `54e1921` 포함 검사 결과 `0`.
- **주의:** 12:23 이전 히스토리의 로컬 브랜치·폴더(예: 예전 작업용 클론)에서는 **절대 푸시하지 않습니다.** 지운 exe와 가리기 전
  개인정보가 다시 올라갑니다. 필요한 변경은 새 클론의 새 브랜치로 옮기세요(`git cherry-pick` 또는 백업 diff 적용). 다른 예전 체크아웃도 같은 방식으로 맞추거나 보관합니다.
- **롤백:** `git -C $SION reset --hard $old` (이전 커밋은 로컬 객체와 번들에 남아 있음). 커밋 안 한 변경은
  `git -C $SION apply <백업 .diff>` 로 되살립니다. 새 클론이었다면 폴더만 지우면 됩니다(아직 운영에 연결되지 않음).

## 2. 런타임을 `packages/aec`로 전환 (20–40분)

런북: [`packages/aec/docs/SWITCH-TO-MONOREPO.ko.md`](../../packages/aec/docs/SWITCH-TO-MONOREPO.ko.md)

### 2-1. 드라이런
- [ ] **왜:** 기존 compose 프로젝트·DB 볼륨을 정확히 감지했는지 확인합니다. 틀리면 빈 DB가 새로 만들어집니다.
- **명령**
  ```powershell
  cd $SION
  powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot <LEGACY_ONTOLOGY>
  docker inspect aec-db --format '{{index .Config.Labels "com.docker.compose.project"}} {{range .Mounts}}{{.Name}} {{end}}'
  ```
- **성공 기준**
  - 출력의 `compose project=<X> db volume=<X>_aec-pgdata` 가 `docker inspect` 결과(프로젝트 `<X>`, 볼륨 `<X>_aec-pgdata`)와 **같음**.
  - `task \AEC\... legacy=True` 목록에 AEC-Bulk-Workers, AEC-Bulk-Census(-Refresh), AEC-Ollama, AEC-Reembed,
    AEC-WSL-Reclaim, AEC-GraphRAG-Refresh 가 보임.
  - 마지막에 `[DRY-RUN] would ...` 계획만 있고 아무것도 바뀌지 않음.
- **롤백:** 해당 없음(변경 없음). 볼륨이 다르면 **중단**하고 `-ComposeProject <X>`로 다시 드라이런.

### 2-2. 실행
- [ ] **명령**
  ```powershell
  powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot <LEGACY_ONTOLOGY> -Apply
  ```
  긴 DWG/PDF 작업 중이면 `-DrainTimeoutMin 30`. 재실행 시 끝난 단계는 `-SkipCompose` `-SkipVenv` `-SkipBackup` 등으로 생략.
- **성공 기준:** 로그 `D:\AECData\bulk\logs\switch-to-monorepo-<시각>.log` 끝에 `warning(s)=0`(또는 WARN 줄이 모두 설명 가능),
  `API .../healthz ok`, 전환 후 `aec-db`가 같은 볼륨을 사용한다는 검사 통과.
- **롤백:** 예전 체크아웃은 건드리지 않습니다. 런북 5절대로 `D:\AECData\switch-backup\<시각>\AEC_*.xml`을 다시 등록하고
  `<LEGACY_ONTOLOGY>`에서 `docker compose up -d db api` → `stop-workers.ps1 -Resume`.

## 3. 전환 결과 검증 (10분)

- [ ] **왜:** 전환 후 API·KG·예약작업이 실제로 새 경로에서 도는지 확인합니다.
- **명령** (토큰은 변수에만 담고 출력하지 않음)
  ```powershell
  cd $SION\packages\aec
  $tok = (Select-String -Path .env -Pattern '^AEC_API_TOKEN=(.*)$').Matches[0].Groups[1].Value
  $h = @{ Authorization = "Bearer $tok" }
  $port = (Select-String -Path .env -Pattern '^AEC_API_HOST_PORT=(\d+)').Matches.Groups[1].Value; if (-not $port) { $port = 58000 }
  Invoke-RestMethod "http://127.0.0.1:$port/healthz"
  Invoke-RestMethod "http://127.0.0.1:$port/v1/kg/stats" -Headers $h | ConvertTo-Json -Depth 3
  Remove-Variable tok, h

  Get-ScheduledTask -TaskPath '\AEC\' | ForEach-Object {
    [pscustomobject]@{ Task = $_.TaskName; State = $_.State; Cmd = ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) [$($_.WorkingDirectory)]" }) -join ' | ' }
  } | Format-Table -Wrap
  Get-ScheduledTask -TaskName 'AutoSync_Code_To_GDrive' -ErrorAction SilentlyContinue | Format-Table TaskName, State
  Get-ScheduledTaskInfo -TaskPath '\AEC\' -TaskName 'AEC-GraphRAG-Refresh' | Format-List LastRunTime, LastTaskResult
  powershell -ExecutionPolicy Bypass -File scripts\ops\graphrag.ps1 stats
  ```
- **성공 기준**
  - `/healthz` 정상, `/v1/kg/stats`에 노드·엣지·커뮤니티 수가 전환 전과 같거나 많음.
  - `\AEC\` 작업의 명령/작업 폴더가 모두 `...\Ontology-platform\packages\aec` 를 가리키고 `<LEGACY_ONTOLOGY>` 경로가 없음.
    AEC-Ops-FinalWrap / AEC-Ops-FinalCheck 는 삭제됨.
  - `AutoSync_Code_To_GDrive` 는 `Disabled`(또는 존재하지 않음). 라이브 DB를 Drive로 복사하면 안 됩니다.
  - `AEC-GraphRAG-Refresh` 의 `LastTaskResult = 0`. 끝나면 `graphrag.ps1 stats` 에서 **FAILED 커뮤니티 0**
    (이전 6건). 남아 있으면 `graphrag.ps1 summarize` 를 한 번 더 실행(FAILED는 자동 재시도·캐시 재사용).
- **롤백:** 2-2의 롤백과 같음. GraphRAG 재색인은 데이터를 지우지 않으므로 롤백 불필요.

## 4. 방화벽: 18080 / 22217 포트 차단 (관리자, 2분)

- [ ] **왜:** 다른 컨테이너(cli-opencode-proxy 18080, ds-free-api 22217)가 `0.0.0.0`에 열려 있어 LAN에 노출됩니다. 아직 안 했을 때만.
- **명령** (오너가 **관리자 PowerShell**에서)
  ```powershell
  Get-NetFirewallRule -Name 'GrokBot-block-*' -ErrorAction SilentlyContinue | Format-Table Name, Enabled
  # 없으면: 운영 방화벽 스크립트 실행 (packages/aec/docs/OPERATIONS.ko.md 의 '방화벽' 절에 있는 경로)
  powershell -ExecutionPolicy Bypass -File <운영 방화벽 스크립트>
  ```
- **성공 기준:** 차단 규칙 2개가 `Enabled=True`. 다른 PC에서 `Test-NetConnection <메인 PC IP> -Port 18080` 이 실패.
- **롤백:** `Remove-NetFirewallRule -Name GrokBot-block-18080, GrokBot-block-22217`

## 5. DB 백업을 DB와 다른 디스크로 (10분)

- [ ] **왜:** 지금 DB(Docker 디스크)와 백업이 **같은 USB 디스크(D:)** 에 있어 디스크 하나가 고장 나면 둘 다 잃습니다.
- **명령**
  ```powershell
  $src = if ($env:AEC_BACKUP_DIR) { $env:AEC_BACKUP_DIR } else { 'D:\AECData\backups' }   # 실제 백업 작업의 -Target 과 맞출 것
  $latest = Get-ChildItem $src -Filter 'aec-db-*.dump' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $dst = 'C:\AECBackup'   # 내장 SSD 또는 다른 드라이브
  New-Item -ItemType Directory -Force $dst | Out-Null
  Copy-Item $latest.FullName $dst
  (Get-FileHash $latest.FullName).Hash -eq (Get-FileHash (Join-Path $dst $latest.Name)).Hash
  ```
  이후 백업 작업이 다른 디스크에도 쓰게 하려면 사용자 환경변수 `AEC_BACKUP_DIR` 을 내장 디스크/Drive 경로로 지정하고
  `scripts\ops\register-backup-task.ps1` 로 재등록(기존 작업 XML 먼저 `Export-ScheduledTask` 로 백업).
- **성공 기준:** 해시 비교 `True`. 백업/복원 절차 자체는 CI(`verify.yml`, PR #47)에서 매번 검증되지만, 실제 덤프로도 가능하면 `scripts\ops\restore-drill.ps1` 로 복원 연습 1회 통과.
- **롤백:** 복사본만 생기므로 롤백 불필요(원본 백업은 그대로). 환경변수를 바꿨다면 이전 값으로 되돌리고 백업한 XML 재등록.

## 6. DB 크래시 원인 추적 (15분, 조사만)

- [ ] **왜:** 2026-10-04 22:01 `aec-db` 크래시(`exited with exit code 2`, WAL 복구 489 s)의 근본 원인이 미확정입니다
  (기록: `packages/aec/docs/OPERATIONS.ko.md` "aec-db 크래시와 복구 시간").
- **명령**
  ```powershell
  docker logs aec-db --since 72h 2>&1 | Select-String -Pattern 'terminated by signal|exit code|out of memory|PANIC|could not write' | Select-Object -Last 40
  wsl -d docker-desktop dmesg 2>$null | Select-String -Pattern 'oom|Out of memory|I/O error|EXT4-fs error' | Select-Object -Last 40
  Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-7)} |
    Where-Object { $_.ProviderName -match 'disk|Ntfs|stor|USB|Hyper-V' -and $_.Level -le 3 } |
    Select-Object -First 30 TimeCreated, ProviderName, Id, Message
  ```
- **성공 기준:** OOM / 디스크 I/O 오류 / USB 리셋 중 하나로 원인을 좁혀 `OPERATIONS.ko.md` 해당 절에 결론을 PR로 추가.
- **롤백:** 해당 없음(읽기 전용).

## 7. `.wslconfig` memory=6GB 적용 확인 (2분)

- [ ] **왜:** RAM 15 GB PC에서 WSL VM이 메모리를 다 쓰지 않도록 상한을 걸었고, 재부팅/WSL 재시작 후에 적용됩니다.
- **명령**
  ```powershell
  Get-Content "$env:USERPROFILE\.wslconfig"
  wsl -d docker-desktop cat /proc/meminfo | Select-String MemTotal
  ```
- **성공 기준:** `.wslconfig` 에 `memory=6GB`, `MemTotal` 이 약 6 GB(≈ 6,000,000 kB 안팎).
- **롤백:** `.wslconfig` 를 바꾸기 전 `.wslconfig.bak-<날짜>` 로 백업, 문제 시 복원 후 `wsl --shutdown`(작업 드레인 후).

## 8. `/review` 승인·반려 (오너 판단, 30–60분)

- [ ] **왜:** SketchUp 0914 지식팩의 분류 후보 **214건** + 워크플로 링크, 맵 관계 **43건**이 `unverified` 상태입니다(이슈 #3: 31노드·43관계, 이슈 #33: SketchUp).
  사람 판단이 필요합니다. 에이전트는 자동 승인하지 않습니다.
- **명령**
  ```powershell
  cd $SION
  .\scripts\sion-local.ps1 start
  Start-Process "http://127.0.0.1:8010/review"
  ```
  일괄 승인·반려(PR #44, 병합됨): 필터로 묶은 뒤 일괄 처리하거나 단축키로 빠르게 판정합니다. 화면의 "추천" 표시는
  참고용일 뿐 자동으로 반영되지 않습니다. API로는 `POST /api/v1/relations/candidates/bulk`(쓰기 권한 필요, 로컬 전용).
- **성공 기준:** `/review` 의 대기 후보 수가 0(또는 의도적으로 보류한 것만 남음). 이슈 #3 닫기, #33 체크리스트 갱신.
- **롤백:** 판정은 이력으로 남습니다. 잘못 판정한 건은 `/review` 에서 다시 반대로 판정(삭제 엔드포인트 없음).

## 9. power-cad-mcp 최신화 (20분)

- [ ] **왜:** main에 #40(문서 동기화), #42(철골 플레이북), #43(`cad_hs_*` 자산 도구 10개, 총 도구 65개), #44(Ask 테스트 결정화)가 병합됐습니다. #45–#48(스킬·자산 파이프라인·headless DXF·`cad_hs_search`)은 20:30 기준 열림 — 병합 여부 확인.
  **오너의 기존 기능 브랜치와 로컬 수정은 그대로 둡니다** → 별도 worktree에서 main을 씁니다.
- **명령**
  ```powershell
  $PCAD = '<power-cad-mcp 기존 체크아웃>'
  git -C $PCAD status --short --branch          # 현재 브랜치·로컬 수정 확인만 (건드리지 않음)
  git -C $PCAD fetch origin
  git -C $PCAD worktree add "$PCAD-main" origin/main
  cd "$PCAD-main"
  powershell -ExecutionPolicy Bypass -File scripts\install_autocad_plugin.ps1   # 빌드 + 플러그인/서버 등록
  # 메인 PC의 HS-STEEL 원본 자산 루트는 C:\HS-STEEL (보조 PC는 다를 수 있음, 예: C:\cad\HSSTEEL)
  # 정본 CAD 자산 DB = 오너 Google Drive 의 PowerCad-Assets 폴더 (하위: hs-steel, hs-steel-blocks, _index)
  $GD = '<GoogleDrive>'   # 이 PC에서 Google Drive 데스크톱 폴더가 마운트된 경로
  [Environment]::SetEnvironmentVariable('HS_STEEL_ASSET_ROOT', 'C:\HS-STEEL', 'User')
  [Environment]::SetEnvironmentVariable('POWER_CAD_HS_REGISTRY', '<hs-steel-cad 체크아웃>\assets\registry\asset-registry.json', 'User')
  [Environment]::SetEnvironmentVariable('POWERCAD_ASSET_DB', "$GD\PowerCad-Assets", 'User')
  Test-Path 'C:\HS-STEEL', "$GD\PowerCad-Assets\hs-steel", "$GD\PowerCad-Assets\hs-steel-blocks", "$GD\PowerCad-Assets\_index"
  ```
  MCP 클라이언트를 재시작한 뒤 도구 목록을 확인합니다.
- **성공 기준:** `Test-Path` 4개 모두 `True`. 도구 65개, `cad_hs_` 로 시작하는 도구 10개
  (power-cad-mcp #48 `cad_hs_search`/`cad_hs_index_status` 가 병합돼 있으면 그만큼 늘어남). `cad_hs_assets {"category":"block","query":"일반사항"}` 결과가 나오고,
  `cad_hs_block_place ... "dry_run": true` 결과의 `path_exists` 가 `true`.
- **롤백:** `git -C $PCAD worktree remove "$PCAD-main"`; 환경변수 삭제; 이전 릴리스 zip으로 `install_autocad_plugin.ps1 -SkipBuild` 재실행.
  기존 브랜치는 처음부터 손대지 않았으므로 그대로입니다.

## 10. hs-steel-cad 최신화 (10분)

- [ ] **왜:** #7 자산 레지스트리(`hs-steel-asset-registry/1`, 자산 819개)가 병합됐습니다. Windows 줄바꿈으로 해시가 어긋나던 문제도 고쳐졌습니다.
- **명령**
  ```powershell
  cd '<hs-steel-cad 체크아웃>'
  git status --short --branch; git switch main; git pull --ff-only    # 로컬 수정이 있으면 worktree 사용 (9번과 같은 방식)
  dotnet run --project tools/AssetRegistry -- --check
  dotnet test HsSteel.sln
  ```
- **성공 기준:** `--check` 종료 코드 0(커밋된 레지스트리가 최신), 테스트 통과.
- **롤백:** `git switch -` 로 이전 브랜치 복귀. `--check` 는 파일을 쓰지 않습니다.

## 11. Sion 로컬 실행·Drive export 확인 (10분)

- [ ] **왜:** Sion API는 라이브 DB를 로컬 디스크에 두고, 커밋된 쓰기마다 스냅샷·그래프를 `SION_STORAGE_ROOT`(Drive 데스크톱 폴더)로 내보냅니다.
- **명령**
  ```powershell
  cd $SION
  [Environment]::GetEnvironmentVariable('SION_STORAGE_ROOT', 'User')
  [Environment]::GetEnvironmentVariable('SION_DATABASE_URL', 'User') -replace '//[^@]*@', '//***@'   # 비밀번호 가림
  .\scripts\sion-local.ps1 start
  .\scripts\sion-local.ps1 status
  Invoke-RestMethod http://127.0.0.1:8010/health
  # /review 판정 1건 등 쓰기 1회 후
  Get-ChildItem $env:SION_STORAGE_ROOT -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName, LastWriteTime
  ```
- **성공 기준:** `status` 에 API(8010) 실행 중, 쓰기 직후 `SION_STORAGE_ROOT` 아래 스냅샷/그래프 파일의 수정 시각이 갱신됨.
  라이브 DB 파일은 Drive 폴더 안에 **없음**.
- **롤백:** `.\scripts\sion-local.ps1 stop`. export는 한 방향 복사라 되돌릴 것이 없습니다.

## 12. 정리 (오너 확인 후, 10분)

- [ ] **왜:** 남은 zip 사본, 오래된 worktree, 예전 venv가 디스크를 차지합니다. **목록을 보여 주고 오너가 확인한 것만** 지웁니다.
- **명령**
  ```powershell
  # 목록만 (삭제 안 함)
  Get-ChildItem "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop" -Filter *.zip |
    Where-Object Name -match 'Ontology|power-cad|hs-steel|ArchOntos|Sion' | Format-Table FullName, Length, LastWriteTime
  git -C $SION worktree list
  git -C $PCAD worktree list
  Get-ChildItem $SION\packages\aec -Directory -Filter '.venv.old-*'
  # 오너가 확인한 항목만
  # git -C <repo> worktree remove <path>;  Remove-Item <확인된 zip>
  ```
- **성공 기준:** 오너가 고른 항목만 삭제, `git worktree prune` 후 목록이 깔끔함.
- **롤백:** zip은 GitHub/Releases/Drive에 원본이 있어 다시 받을 수 있습니다. 예전 `<LEGACY_ONTOLOGY>` 체크아웃은
  며칠 안정 운영을 확인한 뒤에만 지우고, 그 전에는 남겨 둡니다(롤백 경로).

---

## 끝나면

- `docs/STATUS.md` / `docs/STATUS.ko.md` 의 "남은 작업"과 이슈 #33을 갱신하는 PR을 올립니다(개인정보 검사 후).
- 이 파일의 체크 표시와 결과 요약도 같은 PR에 넣습니다. 비밀값·PC 이름·사용자 경로는 넣지 않습니다.
