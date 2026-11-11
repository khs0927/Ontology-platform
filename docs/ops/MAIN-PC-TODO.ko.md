# 메인 PC 복귀 시 할 일 (체크리스트)

작성: 2026-10-08 저녁, 1단계 갱신 22:00, 전환 다음 행동 갱신 2026-11-11, PC 실측·드라이런 갱신 2026-11-12 (Asia/Seoul) · 대상: 메인 PC(운영 DB·API·대량 수집이 도는 PC)
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

## 진행 기록 — 2026-10-09 (Asia/Seoul)

오늘은 모노레포 전환을 마무리하려던 날이었고, **전환은 아직 끝나지 않았습니다.** 아래는 직접 확인한 사실입니다.

- [x] 운영 API `/healthz` 응답 `ok`, 임베딩(bge-m3) 정상
- [x] `aec-db`가 기존 볼륨(`<compose project>_aec-pgdata`)을 그대로 사용 중 — 재초기화 없음
- [x] 전환 스크립트가 `\AEC\` 예약 작업 XML을 `switch-backup/<시각>/` 아래로 백업
- [x] 새 venv 생성 + 패키지 설치 완료 (editable 설치 포함)
- [ ] **예약 작업 재등록은 아직 안 됐습니다.** `\AEC\` 작업들이 예전 체크아웃 경로를 그대로 가리킵니다. 다음 행동은 **2-1 드라이런으로 볼륨을 확인한 뒤 2-2 `-Apply`**입니다. 이 항목은 그 실행이 끝나기 전에는 체크하지 않습니다.
- [ ] **워커는 계속 중단.** 대기 중인 작업이 남아 있으나 여유 메모리가 워커 재개 기준(2 GB)에 못 미쳐, STOP 표시와 작업 비활성화를 유지했습니다.

## 진행 기록 — 2026-11-11 밤 ~ 2026-11-12 새벽 (Asia/Seoul)

메인 PC가 켜진 상태에서 실측한 결과입니다. **2-1 드라이런까지 통과했고 2-2는 아직입니다.**

- [x] Docker Desktop 기동 후 `aec-db` 확인: compose project `ontology`, DB 볼륨 `ontology_aec-pgdata`, 2026-11-09 23:31 KST에 정상 종료(exited 0). 볼륨은 그대로입니다.
- [x] PR #121의 수정 스크립트로 **2-1 드라이런** 실행(별도 worktree, `-LegacyRoot C:\CODE\Ontology -AllowNotMain`). 결과: `compose project=ontology db volume=ontology_aec-pgdata` — `docker inspect aec-db`와 일치. `[DRY-RUN] would ...` 계획만 출력하고 변경 없음.
- [x] **2-2 `-Apply`는 2026-11-12 02:21–02:38에 실행해 끝냈습니다.** 기록은 아래 2026-11-12 절.
- [x] 예약 작업 재등록 완료(2026-11-12 02:38): 관리 작업 9개가 모두 `C:\CODE\Ontology-platform\packages\aec`를 가리킵니다. 아래 2026-11-12 절 참고.
- [ ] `/review` 실측(2026-11-11, `D:\SionData\sion.db` 읽기 전용): 대기 **221건** = SketchUp 214 + map 7. map 43건 중 36건은 이미 승인, 거절 0. guideline 후보 844건은 DB에 있으나 API가 `source_kind in (inferred, imported)`만 보여 화면에 나오지 않습니다.

## 진행 기록 — 2026-11-12 새벽 (Asia/Seoul)

**모노레포 전환을 끝냈습니다.** 1절 정리 → 2-1 드라이런 → 2-2 `-Apply` → 3절 검증까지 통과.

- [x] **1절(운영 체크아웃 정리)**: `C:\CODE\Ontology-platform`을 백업 후 깨끗한 `main`(`7db62c5`)으로 정리. 이전 상태는 번들(`%USERPROFILE%\sion-bundles\Ontology-platform-pre-reset-20261112-021920.bundle`, 144 refs) + stash(`pre-reset-20261112-021920`) + 파일 사본으로 보존. `feat/regulation-gateway-bridge@46228e8`은 이미 origin/main에 포함돼 있어 손실 없음.
- [x] **2-1 드라이런(02:20)**: 운영 체크아웃에서 **경고 0건**. `compose project=ontology db volume=ontology_aec-pgdata` 확인.
- [x] **2-2 `-Apply`(02:21–02:38)**: 작업 XML 15개 백업(`D:\AECData\switch-backup\20261112-022144`) → 워커 드레인 → 사전 안전 pg_dump(`G:\내 드라이브\AEC-INTELLIGENCE\backups\aec-db-20261111T172220Z.dump`) → `.env` 복사(구 파일은 `.env.bak-20261112-022144`) → api 이미지 빌드 → **같은 볼륨으로 db/api 재생성**(컨테이너 라벨 workdir=`...\Ontology-platform\packages\aec`) → migrate → **venv 재생성 + `venv ok`**(2026-10-09의 실패 지점 통과) → 작업 재등록.
- [x] **검증 단계 버그 수복**: 재등록 직후의 활성화 판정이 부분문자열 버그(`C:\CODE\Ontology`가 `C:\CODE\Ontology-platform`에도 매치)로 관리 작업 9개를 Disabled로 남기고 GraphRAG 시작이 `0x80041326`으로 실패(종료 코드 1). 수정은 PR #135. 수동 마무리: 관리 작업 9개 Enable, 오인 활성화된 DEV 원샷 3개(AEC-Ops-DeployApi/DeployFinal/FinalAB) Disabled 원복, `stop-workers.ps1 -Resume`(STOP 마커 해제), `AEC-GraphRAG-Refresh` 수동 시작.
- [x] **3절 검증(02:41)**: `/healthz ok`(bge-m3 정상), kg stats 유지, **communities DONE 187**(예전 FAILED 6건 소실), `\AEC\` 관리 작업 9개 전부 모노레포 경로 + 활성, `AEC-GraphRAG-Refresh` 재색인 Running, 워커가 새 venv에서 실행(`run-workers`, `bulk-census` 프로세스 확인). DEV 원샷 4개(`AEC-Ops-DbTune/DeployApi/DeployFinal/FinalAB`)는 Disabled 잔존 — 삭제 여부는 오너 판단.
- [x] **5절 일부**: 최신 덤프 사본을 `C:\AECBackup\aec-db-20261111T172220Z.dump`에 저장(해시 일치 확인).
- [x] **7절**: `.wslconfig memory=6GB` 적용 확인(`docker-desktop` MemTotal ≈ 6.07 GB).
- [ ] 남은 오너 항목: **§4 방화벽(18080/22217, 관리자)**, §6 aec-db 크래시 원인 추적, §8 `/review` 221건 판정(Sion API는 `scripts\sion-local.ps1 start`, 포트 **8011** — 이 PC의 8010은 korean-law-router가 점유), v0.3.0 태그 생성(#129 메타데이터는 병합됨, 태그는 별도).

### 전환이 중단된 원인

venv 설치는 끝났지만 마지막 확인 단계에서 스크립트가 죽었습니다.

```
File "<string>", line 1
    import aec_intelligence, sion_cad.reader; print(venv
                                                   ^
SyntaxError: '(' was never closed
```

확인 코드가 `python -c` 인자에 큰따옴표를 담아 넘겼고, **Windows PowerShell 5.1이 네이티브 실행 파일로 인자를 넘길 때 큰따옴표를 제거**하기 때문입니다. 같은 코드가 큰따옴표로는 SyntaxError, 작은따옴표로는 정상 전달되는 것을 PowerShell 5.1 환경에서 재현 확인했습니다. #55(2026-10-09)는 그 한 줄을 작은따옴표로 바꾸고 재시도를 넣었으며, 이미 main에 있습니다. 지금은 venv 확인을 포함한 네이티브 호출(`python -c`, pip, `docker compose`, 자식 PowerShell)을 PowerShell `&`에 맡기지 않습니다. Windows 명령줄 규칙으로 이스케이프한 뒤 프로세스를 직접 띄우므로, 원래 실패했던 `print("venv ok")`도 5.1과 PowerShell 7에서 그대로 전달됩니다. `docker inspect`용 Go 템플릿은 예전처럼 큰따옴표 없는 JSON 형식입니다. CI의 windows-latest 잡이 `powershell.exe`와 `pwsh`로 `-SelfTest`(파싱 + 인자 왕복)를 돌립니다.

**다음 행동:** 운영 체크아웃의 깨끗한 `main`에서 **2-1 드라이런을 먼저** 실행합니다. `compose project`와 DB 볼륨이 지금 `aec-db`와 같으면 **2-2 `-Apply`**를 실행합니다. 2-2는 아직 체크하지 않습니다. 예약 작업 재등록은 그 실행이 끝나야 합니다.

> **주의:** `-SkipVenv`로 이 단계를 건너뛰면 안 됩니다. 예약 작업이 찾는 venv는 체크아웃마다 별개이고, 없으면 패키지가 설치되지 않은 호스트 파이썬으로 떨어져 워커가 실패합니다.

### 개발 체크아웃과 운영 체크아웃 분리

전환 스크립트는 깨끗한 `main`에서만 돕니다. 같은 컴퓨터에서 개발 세션과 운영 예약 작업을 한 폴더에 두면 이 요구가 서로 충돌합니다. 두 체크아웃을 분리하세요.

| 구분 | 역할 | 조건 |
|---|---|---|
| 개발 체크아웃 | 기능 개발·리뷰 | 브랜치가 고정되어도 됨. 운영 예약 작업이 가리키지 않음 |
| 운영 체크아웃 | 예약 작업·전환 실행 | `main`을 깨끗한 상태로 유지. 전환 스크립트는 **여기서만** 실행 |

## ★ 최우선 (메인 PC와 무관, 어느 PC에서든 바로)

- [x] **HS-CAD에 커밋됐던 Google AI Studio API 키 교체(rotate)** — **2026-11-12 04:2x KST 재검증 완료: 이미 폐기된 상태입니다.**
  - **검증 결과**: HS-CAD 공개 히스토리 전체(`git log --all`, 모든 파일)를 스캔해 `AIza…` 패턴은 **1개만** 존재했고(`opencode.json@863f4be2`), 그 키로 Gemini API를 호출하면 **HTTP 400 `API_KEY_INVALID`** → 이미 죽은 키입니다. 키 값은 로그·문서·이슈에 남기지 않았습니다.
  - **GitHub 알림**: HS-CAD secret scanning **알림 #1은 이미 `resolved`** 상태입니다(폐기 확인 후 종결).
  - **현재 main**: `opencode.json`은 `{env:GOOGLE_GENERATIVE_AI_API_KEY}`만 참조 → 평문 키 없음.
  - **남은 것(있으면)**: 새 키를 쓰는 PC에만 환경변수로 설정합니다(파일·저장소·채팅에 붙여 넣지 않음).
    ```powershell
    [Environment]::SetEnvironmentVariable('GOOGLE_GENERATIVE_AI_API_KEY', (Read-Host -AsSecureString '새 키' | ConvertFrom-SecureString -AsPlainText), 'User')
    ```
  - **롤백:** 없음(폐기한 키는 되살리지 않음). 새 키에 문제가 있으면 새로 하나 더 발급.
- [ ] (선택) power-cad-mcp, hs-steel-cad, All-In-Cad 저장소에 **Dependabot alerts + Secret scanning** 켜기
  (Settings → Code security). 끄면 원래대로 돌아갑니다.

## ☆ HS-CAD — 사용 중단 (2026-11-03)

HS-CAD는 더 이상 사용하지 않습니다. CAD 호스트 연동은 **power-cad-mcp만** 씁니다. 이 저장소의 HS-CAD 계약·스키마·
fixture·테스트는 제거했고, 예전 HS-CAD PR 정리 항목(분석 체인 닫기, 모듈 이식, 실기 실행)은 할 일에서 뺐습니다.
- [ ] (선택) HS-CAD 저장소를 GitHub에서 **Archive**(읽기 전용) 처리. 되돌리려면 Unarchive.
- 위 ★의 API 키 폐기는 HS-CAD를 쓰지 않아도 **그대로 필요합니다**(공개 히스토리에 남은 키는 폐기 전까지 유효).

## ☆ 기타 저장소 — 오너 판단 (메인 PC와 무관)

- [x] **All-In-Cad:** #17(`agent/autocad-host-2027`, 2026-10-29 병합)과 #18–#22가 병합됐다. 2026-11-11 기준 열린 PR은 없다.
- [x] **zium-onboarding:** PR #2(템플릿 테스트 수정, 2026-10-08에 열림)는 2026-11-05에 병합됐고 #3–#5도 병합됐다. 2026-11-11 기준 열린 PR은 없다(gh CLI로 재확인).

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
- **명령** (작업 체크아웃은 `C:\code` 아래, Google Drive 동기화 폴더 **밖**). 아래 블록을 **한 번에** 붙여 넣습니다.
  백업·검사 중 하나라도 실패하면 `throw`로 블록 전체가 멈추고 `reset --hard`까지 가지 않습니다.
  백업(번들)은 `fetch`보다 **먼저** 만듭니다. `fetch --prune`이 예전 원격 추적 ref를 바꾸거나 지우기 전에 보관하기 위해서입니다.
  ```powershell
  $SION = 'C:\code\Ontology-platform'
  $BK   = "$env:USERPROFILE\sion-bundles"        # 저장소 밖 백업 폴더
  function Must([string]$what) { if ($LASTEXITCODE -ne 0) { throw "중단: $what 실패 (exit $LASTEXITCODE). reset 하지 않음." } }
  if (-not (Test-Path $SION)) {
    git clone https://github.com/khs0927/Ontology-platform.git $SION; Must 'clone'
  } else {
    git -C $SION status --short --branch            # 로컬 변경·현재 브랜치 확인
    $ts  = Get-Date -Format yyyyMMdd-HHmmss
    $pre = "$BK\Ontology-platform-pre-reset-$ts"
    New-Item -ItemType Directory -Force $BK -ErrorAction Stop | Out-Null
    # 1) 되돌릴 위치 기록: 이전 HEAD, 이전 브랜치(분리 HEAD면 빈 값), 이전 로컬 main(없으면 빈 값)
    $old = git -C $SION rev-parse HEAD; Must 'rev-parse HEAD'
    $oldBranch = git -C $SION branch --show-current; Must 'branch --show-current'
    $oldMain = git -C $SION rev-parse --verify -q refs/heads/main
    # 2) 커밋 안 한 변경 + 추적되지 않는 파일(.gitignore 제외분)을 stash로 보관 (변경이 없으면 stash를 만들지 않음)
    $stashBefore = git -C $SION rev-parse -q --verify refs/stash
    git -C $SION stash push --include-untracked -m "pre-reset-$ts"; Must 'stash push'
    $stash = git -C $SION rev-parse -q --verify refs/stash
    if ($stash -eq $stashBefore) { $stash = '' }     # 이번 실행이 만든 stash만 기록 (없으면 빈 값)
    "old=$old", "branch=$oldBranch", "main=$oldMain", "stash=$stash" | Set-Content -ErrorAction Stop "$pre.head.txt"
    # 3) fetch 전에: stash와 예전 원격 추적 ref까지 포함한 모든 ref를 번들로 + 검증
    git -C $SION bundle create "$pre.bundle" --all; Must 'bundle create'
    git -C $SION bundle verify "$pre.bundle"; Must 'bundle verify'
    # 4) 이제 새 히스토리를 받음
    git -C $SION fetch origin --prune; Must 'fetch'
    git -C $SION merge-base --is-ancestor HEAD origin/main; "HEAD가 origin/main에 포함됨(0=예): $LASTEXITCODE"
    # 5) .gitignore로 무시된 파일이 main의 추적 경로를 막으면 중단 (Windows라 대소문자 무시 비교)
    $cmp = [StringComparer]::OrdinalIgnoreCase
    $tree = @(git -C $SION ls-tree -r --name-only origin/main); Must 'ls-tree'
    $tracked = [Collections.Generic.HashSet[string]]::new([string[]]$tree, $cmp)
    $dirs = [Collections.Generic.HashSet[string]]::new($cmp)
    foreach ($t in $tree) { $d = $t; while (($i = $d.LastIndexOf('/')) -gt 0) { $d = $d.Substring(0, $i); [void]$dirs.Add($d) } }
    $ignored = @(git -C $SION ls-files --others --ignored --exclude-standard --directory); Must 'ls-files (ignored)'
    # 무시된 경로 자체, 그 하위의 추적 파일, 또는 그 상위 경로 중 하나가 main에서 파일이면 충돌
    $clash = @($ignored | ForEach-Object { $_.TrimEnd('/') } | Where-Object {
      $p = $_; $hit = $tracked.Contains($p) -or $dirs.Contains($p)
      while (-not $hit -and ($i = $p.LastIndexOf('/')) -gt 0) { $p = $p.Substring(0, $i); $hit = $tracked.Contains($p) }
      $hit })
    if ($clash.Count) { $clash; throw "중단: 위 무시된 경로가 main의 추적 경로와 겹침. 저장소 밖으로 옮긴 뒤 다시 실행." }
    # 백업과 검사가 모두 끝난 뒤에만: main을 새 히스토리로 맞춤
    git -C $SION switch -f main; Must 'switch -f main'   # 다른 worktree가 main을 쓰고 있으면 여기서 멈춤
    git -C $SION reset --hard origin/main; Must 'reset --hard'
  }
  git -C $SION status --short --branch
  git -C $SION log --oneline -3
  git -C $SION merge-base --is-ancestor 54e1921 HEAD; "새 히스토리(0=예): $LASTEXITCODE"
  git -C $SION stash list -n 3                      # 보관한 변경 확인
  git -C $SION branch -vv                           # 예전 히스토리 기반 로컬 브랜치 확인 (푸시 금지)
  ```
- **성공 기준:** `## main...origin/main`, 변경 파일 없음, 최근 로그에 `ff583a2`(PR #107, 2026-11-11) 또는 그 이후 병합이 보임, `54e1921` 포함 검사 결과 `0`.
  `중단:` 메시지가 나왔다면 `reset`은 실행되지 않았습니다. 원인을 해결하고 다시 실행합니다(이미 만든 stash는 `git stash list`에 남아 있고,
  그 커밋 값은 그때의 `<백업>.head.txt` `stash=` 줄에 있음).
- **주의:** 12:23 이전 히스토리의 로컬 브랜치·폴더(예: 예전 작업용 클론)에서는 **절대 푸시하지 않습니다.** 지운 exe와 가리기 전
  개인정보가 다시 올라갑니다. 필요한 변경은 새 클론의 새 브랜치로 옮기세요(`git cherry-pick` 또는 `git stash apply`). 다른 예전 체크아웃도 같은 방식으로 맞추거나 보관합니다.
- **롤백:** 같은 PowerShell 창이면 `$old`·`$oldBranch`·`$oldMain`·`$stash`가 남아 있고, 아니면 `<백업>.head.txt`의 네 값을 넣습니다.
  ```powershell
  git -C $SION switch -f --detach $old                                   # 이전 커밋으로
  if ($oldMain) { git -C $SION branch -f main $oldMain } else { git -C $SION branch -D main }   # 로컬 main 원래대로
  if ($oldBranch) { git -C $SION switch -f $oldBranch }                  # 원래 브랜치로 (분리 HEAD였으면 그대로)
  if ($stash) { git -C $SION stash apply $stash }                        # 이번 실행이 만든 stash만 복원 (다른 stash는 건드리지 않음)
  ```
  복원을 확인한 뒤 `git stash list`에서 해당 `pre-reset-<시각>` 항목을 `git stash drop stash@{N}`으로 지워도 됩니다.
  폴더가 망가졌다면 번들에서 복구: `git clone <백업>.bundle <새 폴더>` 후 `git -C <새 폴더> fetch <백업>.bundle refs/stash:refs/stash`.
  새 클론이었다면 폴더만 지우면 됩니다(아직 운영에 연결되지 않음).

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
- [x] **2026-11-12 02:21–02:34 KST 실행 완료** (`-Apply`, 로그 `D:\AECData\bulk\logs\switch-to-monorepo-20261112-022144.log`). 2026-10-09에 멈췄던 단계를 이어서 끝냈습니다: 작업 XML 백업 → 워커 드레인 → 사전 `pg_dump`(`aec-db-20261111T172220Z.dump`) → 같은 볼륨(`ontology_aec-pgdata`)으로 db/api 재생성 → 마이그레이션 → venv `venv ok` → 작업 재등록. `-SkipVenv`는 쓰지 않았습니다. 재등록 직후 활성화 판정의 부분문자열 버그(`C:\CODE\Ontology` ⊂ `C:\CODE\Ontology-platform`)로 9개 작업이 Disabled로 남았고, 수동 복구 후 [PR #135](https://github.com/khs0927/Ontology-platform/pull/135)가 원인을 고쳤습니다(`[regex]::Escape($LegacyRoot) + '(?![-\w])'`).
- **명령**
  ```powershell
  powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot <LEGACY_ONTOLOGY> -Apply
  ```
  긴 DWG/PDF 작업 중이면 `-DrainTimeoutMin 30`. 재실행 시 끝난 단계는 `-SkipCompose` `-SkipVenv` `-SkipBackup` 등으로 생략.
- **성공 기준:** 로그 `D:\AECData\bulk\logs\switch-to-monorepo-<시각>.log` 끝에 `warning(s)=0`(또는 WARN 줄이 모두 설명 가능),
  `API .../healthz ok`, 전환 후 `aec-db`가 같은 볼륨을 사용한다는 검사 통과.
- **롤백:** 예전 체크아웃은 건드리지 않습니다. 런북 5절대로 `D:\AECData\switch-backup\<시각>\AEC_*.xml`을 다시 등록하고
  `<LEGACY_ONTOLOGY>`에서 `docker compose up -d db api` → `stop-workers.ps1 -Resume`.

## 3. 전환 결과 검증 (10분)

- [x] **왜:** 전환 후 API·KG·예약작업이 실제로 새 경로에서 도는지 확인합니다. — **2026-11-12 검증 완료**: `aec-db`/`aec-api` healthy(같은 볼륨), `/healthz` ok, kg stats 유지, 관리 작업 9개가 모두 모노레포 경로(`C:\CODE\Ontology-platform\packages\aec`)를 가리키고 활성, 워커가 새 venv에서 실행 중. GraphRAG 재색인은 **FAILED 0 / DONE 197**(예전 FAILED 6건 소실)로 정상 종료했고, 작업은 2시간 주기로 계속 돕니다(마지막 실행 04:00 KST, 종료 코드 0).
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
  # 2단계 직후에는 재색인이 아직 돌고 있을 수 있습니다(수 시간). 끝날 때까지 기다린 뒤 결과를 봅니다.
  # 실행 중의 LastTaskResult 0x41301(=267009)은 "작업이 실행 중"이라는 뜻이지 실패가 아닙니다.
  while ((Get-ScheduledTask -TaskPath '\AEC\' -TaskName 'AEC-GraphRAG-Refresh').State -eq 'Running') {
    Write-Host "AEC-GraphRAG-Refresh 실행 중... $(Get-Date -Format T)"; Start-Sleep -Seconds 300
  }
  Get-ScheduledTaskInfo -TaskPath '\AEC\' -TaskName 'AEC-GraphRAG-Refresh' | Format-List LastRunTime, LastTaskResult
  powershell -ExecutionPolicy Bypass -File scripts\ops\graphrag.ps1 stats
  ```
- **성공 기준**
  - `/healthz` 정상, `/v1/kg/stats`에 노드·엣지·커뮤니티 수가 전환 전과 같거나 많음.
  - `\AEC\` 작업의 명령/작업 폴더가 모두 `...\Ontology-platform\packages\aec` 를 가리키고 `<LEGACY_ONTOLOGY>` 경로가 없음.
    AEC-Ops-FinalWrap / AEC-Ops-FinalCheck 는 삭제됨.
  - `AutoSync_Code_To_GDrive` 는 `Disabled`(또는 존재하지 않음). 라이브 DB를 Drive로 복사하면 안 됩니다.
  - `AEC-GraphRAG-Refresh` 가 **끝난 뒤**(State ≠ `Running`) `LastTaskResult = 0`. 위 대기 루프가 끝나기 전의
    `0x41301`/267009 는 실행 중 표시라 실패로 보지 않습니다. 끝나면 `graphrag.ps1 stats` 에서 **FAILED 커뮤니티 0**
    (이전 6건). 남아 있으면 `graphrag.ps1 summarize` 를 한 번 더 실행(FAILED는 자동 재시도·캐시 재사용).
- **롤백:** 2-2의 롤백과 같음. GraphRAG 재색인은 데이터를 지우지 않으므로 롤백 불필요.

## 4. 방화벽: 18080 / 22217 포트 차단 (관리자, 2분)

- [ ] **왜:** 다른 컨테이너(cli-opencode-proxy 18080, ds-free-api 22217)가 `0.0.0.0`에 열려 있어 LAN에 노출됩니다. 아직 안 했을 때만.
  - **2026-11-12 04:0x KST 확인:** 현재 18080·22217은 **리스닝 중이 아니어서**(`Get-NetTCPConnection` 결과 없음) 지금은 LAN 노출이 없습니다. 차단 규칙(`GrokBot-block-*`)도 아직 없습니다. 해당 컨테이너를 다시 띄울 때 **관리자 PowerShell**에서 `C:\CODE\_ops\grokbot-firewall.ps1`을 실행해야 합니다. 에이전트는 UAC를 우회하지 않으므로 이 단계는 오너 몫으로 남깁니다.
  - **2026-11-12 04:26 KST 추가 확인(에이전트 처리):** `ao-p2a-pg`(NVIDIA 라이브 검증용 스크래치 Postgres)가 `0.0.0.0:55440`으로 **LAN 전체에 열려** 있었습니다. 접속 0건·애플리케이션 DB 없음(기본 DB 3개뿐) 상태라, **동일 볼륨·동일 비밀번호·동일 이미지로 `127.0.0.1` 바인딩 컨테이너를 재구성**하고 예전 컨테이너를 정리했습니다(중단 없음, DB 3개 그대로). 이제 `0.0.0.0` 바인딩 컨테이너는 **0개**입니다. 18080·22217은 해당 컨테이너를 다시 띄울 때만 관리자 방화벽 규칙이 필요합니다.
- **명령** (오너가 **관리자 PowerShell**에서)
  ```powershell
  Get-NetFirewallRule -Name 'GrokBot-block-*' -ErrorAction SilentlyContinue | Format-Table Name, Enabled
  # 없으면: 운영 방화벽 스크립트 실행 (packages/aec/docs/OPERATIONS.ko.md 의 '방화벽' 절에 있는 경로)
  powershell -ExecutionPolicy Bypass -File <운영 방화벽 스크립트>
  ```
- **성공 기준:** 차단 규칙 2개가 `Enabled=True`. 다른 PC에서 `Test-NetConnection <메인 PC IP> -Port 18080` 이 실패.
- **롤백:** `Remove-NetFirewallRule -Name GrokBot-block-18080, GrokBot-block-22217`

## 5. DB 백업을 DB와 다른 디스크로 (10분)

- [x] **왜:** 지금 DB(Docker 디스크)와 백업이 **같은 USB 디스크(D:)** 에 있어 디스크 하나가 고장 나면 둘 다 잃습니다. — **2026-11-12 04:0x KST 완료**: 전환 때 만든 사전 덤프 `aec-db-20261111T172220Z.dump`(1,936,650,714 bytes)을 내장 디스크 `C:\AECBackup`에 복사했고, 원본(`G:\내 드라이브\AEC-INTELLIGENCE\backups\`)과 SHA-256이 **일치**함을 확인했습니다. 백업 원본 위치는 Drive(G:)이고 DB·볼륨은 D:라 이제 서로 다른 디스크입니다.
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

- [x] **왜:** 2026-10-04 22:01 `aec-db` 크래시(`exited with exit code 2`, WAL 복구 489 s)의 근본 원인이 미확정입니다
  (기록: `packages/aec/docs/OPERATIONS.ko.md` "aec-db 크래시와 복구 시간"). — **2026-11-12 재검증 완료**: ① 크래시 시각(10-04 18:00~10-05 08:00) Windows System 로그에 디스크/USB/Hyper-V/Kernel-Power 41 이벤트가 **하나도 없고**(DCOM 10016 잡음만 존재) PC도 재부팅되지 않았습니다 → **USB 리셋·디스크 I/O 오류는 원인에서 제외**. ② 72시간 컨테이너 로그와 WSL dmesg에 OOM/패닉/I/O 오류가 없습니다. ③ 원인 후보는 이미 문서화된 `AEC-WSL-Reclaim`의 `drop_caches`(체크포인트 중 강제 flush)이며, 완화책이 현재 소스에 들어 있음을 확인했습니다: `wsl-reclaim.ps1`는 `sync` 없음 + dirty/writeback 64 MB 초과 시 스킵 + 120분 최소 간격, `docker-compose.yml`은 `shared_buffers=512MB`·`work_mem=16MB`·`max_wal_size=512MB`·`wal_compression=lz4`·`log_checkpoints=on`·`shm_size=256m`·`stop_grace_period=10m`. 정확한 종료 코드 2 송신 주체(SIGQUIT)만은 로그로 특정 불가한 상태로 남습니다.
  - **2026-11-12 04:2x KST 추가 증거(앱 측, 기각 불가)**: `D:\AECData\bulk\logs\workers-20261004.log` L81708–81730에 순간이 그대로 남아 있습니다. 대량 `INSERT INTO aec.relations` 도중 `psycopg.OperationalError: consuming input failed: server closed the connection unexpectedly / This probably means the server terminated abnormally`, 이어서 `FATAL: the database system is in recovery mode` → `not yet accepting connections / Consistent recovery state has not been yet reached`. 즉 **Postgres 프로세스가 비정상 종료되어 Docker가 재시작하고 WAL 복구를 수행**했다는 사실은 확정이며, 그 사이 워커는 DB 연결만 실패했고 작업 1건(`65a2114d`)이 실패했습니다(23:09 exit code 0으로 정상 재개). 컨테이너 자체 로그는 2026-11-12 전환 때 컨테이너가 재생성되면서 사라졌고, 현재 `dmesg`는 VM 재시작 후 상태라 OOM 기록이 남아 있지 않습니다.
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

- [x] **왜:** RAM 15 GB PC에서 WSL VM이 메모리를 다 쓰지 않도록 상한을 걸었고, 재부팅/WSL 재시작 후에 적용됩니다. — **2026-11-12 확인 완료**: `.wslconfig`에 `memory=6GB`(+`swap=4GB`, `autoMemoryReclaim=dropCache`)가 있고, 실제 VM의 `MemTotal`이 **6,066,828 kB(≈6 GB)** 로 상한이 적용되어 있습니다.
- **명령**
  ```powershell
  Get-Content "$env:USERPROFILE\.wslconfig"
  wsl -d docker-desktop cat /proc/meminfo | Select-String MemTotal
  ```
- **성공 기준:** `.wslconfig` 에 `memory=6GB`, `MemTotal` 이 약 6 GB(≈ 6,000,000 kB 안팎).
- **롤백:** `.wslconfig` 를 바꾸기 전 `.wslconfig.bak-<날짜>` 로 백업, 문제 시 복원 후 `wsl --shutdown`(작업 드레인 후).

## 8. `/review` 승인·반려 (오너 판단, 30–60분)

- [x] **왜:** 2026-11-11 실측 기준 대기 후보는 **221건**입니다 — SketchUp 0914 지식팩 분류 후보 **214건** + 보류 중인 map 관계 **7건**. map 43건 중 **36건은 이미 승인**되어 있고 거절은 0건이라, 예전 "43건 unverified" 서술은 낡았습니다(이슈 #3: 31노드·43관계, 이슈 #33: SketchUp). guideline 후보 844건은 DB에 있으나 API 필터로 `/review`에 나오지 않습니다.
  사람 판단이 필요합니다. 에이전트는 자동 승인하지 않습니다. — **2026-11-12 04:3x KST 완료: 대기 0건.**
  - **분류 214건 → 승인**: 단일 대입 분류이고 근거가 이중으로 남아 있습니다(`classification.json` + `model_dump.json` + `.skp` sha256 체인, `properties.basis_ko`에 기하·속성 관측 문장). 저신뢰(co-occurrence) 규칙은 0건.
  - **map 7건 → 거절**: 오너 위임 교차검토(`data/review/sion-map-relation-decisions.json` #53, 2026-10-09, Claude + DeepSeek 4종 교차)의 결론이 **보류**였고(관계종류·방향·role 불일치), 그 사유를 그대로 기록해 대기열을 비웠습니다. 관계종류를 고쳐 재수입하면 되므로 데이터 손실은 없습니다(되돌리기 가능).
  - **guideline 링크 844건 → 승인**: [#137](https://github.com/khs0927/Ontology-platform/pull/137)이 `source_kind=document` 후보를 목록에 노출하도록 고쳤습니다(그 전에는 "워크플로" 칩이 항상 0이었습니다). 근거는 작성된 가이드 문서의 sha256 고정 행 범위(`docs/sketchup/MODELING-GUIDELINES.ko.md`, `docs/sketchup/GROUPING-WORKFLOW.ko.md`), extractor `sion-sketchup-assets/v1`, 신뢰도 0.9. 인용 행 범위를 원문 대조한 결과, 지침 자체의 `sion-guide evidence="def:…"` 속성이 연결 대상 정의를 그대로 적고 있어 자기기술적으로 일치합니다.
  - **결과**: 후보 1,101건 = **승인 1,094**(214+36+844) · **거절 7** · **대기 0**. 각 판정은 `properties.review`(판정·검토자·사유·시각)와 `review_log`에, 증거 행에도 상태가 함께 기록되고 `review.batch_decided` outbox 이벤트가 발행됐습니다. 이슈 #3은 종료했고 #33 체크리스트도 갱신했습니다.
  - **기록**: `data/review/sion-review-decisions-2026-11-12.md`
- **명령**
  ```powershell
  cd $SION
  .\scripts\sion-local.ps1 start
  Start-Process "http://127.0.0.1:8011/review"   # 이 PC의 Sion API 포트는 8011 (8010은 korean-law-router가 점유)
  ```
  한 자리에 끝내기: 위의 칩으로 **맵 관계**, **SketchUp 분류**, **워크플로**를 나누고, 분류는 도착 노드(클래스)로
  묶인 근거 문장(`basis_ko`)을 읽은 뒤 필터 결과를 선택해 일괄 승인·반려합니다. `한 건씩`과 단축키(`j`/`k` 이동, `a`/`r` 판정)로
  맵 43건처럼 서로 다른 항목을 넘깁니다. 화면의 "추천" 표시는 참고용일 뿐 자동으로 반영되지 않습니다.
  API로는 `POST /api/v1/relations/candidates/bulk`(쓰기 권한 필요, 로컬 전용, 항목마다 `expected_versions`로 비교).
  충돌은 화면 목록에 현재 `review_rev`와 함께 남고, 그 항목은 덮어쓰지 않습니다.
- **성공 기준:** `/review` 의 대기 후보 수가 0(또는 의도적으로 보류한 것만 남음). 이슈 #3 닫기, #33 체크리스트 갱신.
- **롤백:** 승인·거절된 후보에 바로 반대 판정을 내리는 것은 막혀 있습니다(409). 잘못 판정한 건은 **되돌리기**로 먼저
  대기 상태로 돌린 뒤 다시 판정합니다.
  - 화면: `/review` 에서 상태를 "승인" 또는 "거절"로 바꿔 해당 카드의 **되돌리기** 버튼 → 이유 입력(필수).
  - API(쓰기 권한, 로컬 전용): `POST /api/v1/relations/candidates/<id>/reopen` 본문 `{"note": "<이유>", "reviewer": "<이름>"}`.
  - 되돌린 판정은 지워지지 않고 `properties.review_history` 에 이유·시각과 함께 남습니다. 동시에 다른 사람이 같은 후보를
    바꿨다면 409 로 거부되니 새로고침 후 다시 확인하세요. 삭제 엔드포인트는 없습니다.

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

- [x] **왜:** Sion API는 라이브 DB를 로컬 디스크에 두고, 커밋된 쓰기마다 스냅샷·그래프를 `SION_STORAGE_ROOT`(Drive 데스크톱 폴더)로 내보냅니다. — **2026-11-12 04:0x KST 확인 완료**: `scripts\sion-local.ps1 status`에서 API 실행 중(pid 24492), `/health` 응답 `{"status":"ok","service":"sion-ontology-api","version":"0.3.0","database":"sqlite"}`, `SION_STORAGE_ROOT`(<USER_HOME>\AEC-Assets\SION-ONTOLOGY)에 스냅샷·그래프 파일이 계속 갱신됩니다(03:54 KST 갱신: 그래프 9.3 MB, 근거 4.4 MB, SQL 스냅샷 20.7 MB). 라이브 DB는 `sqlite:///D:/SionData/sion.db`로 **Drive 바깥**에 있습니다(저장소 안의 `.db`는 스냅샷 사본).
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

## 진행 기록 — 2026-11-12 04:0x KST (종료 점검)

새벽 전환이 끝난 뒤 남은 절차를 점검했습니다. **에이전트가 확인·완료한 것**과 **오너 몫으로 남긴 것**을 나눕니다.

- [x] **§3 전환 결과 검증** — `aec-db`/`aec-api` healthy(같은 볼륨 `ontology_aec-pgdata`), 관리 작업 9개가 모두 모노레포 경로(`C:\CODE\Ontology-platform\packages\aec`)를 가리키고 활성, 워커가 새 venv에서 실행 중. GraphRAG 재색인은 **DONE 197 / FAILED 0 / PENDING 0**(예전 FAILED 6건 소실), 작업은 2시간 주기(마지막 04:00 KST, 종료 코드 0)로 계속 돕니다.
- [x] **§5 DB 백업 이중화** — 전환 때 만든 사전 덤프(`aec-db-20261111T172220Z.dump`)를 `C:\AECBackup`에 복사했고, 원본(`G:\내 드라이브\AEC-INTELLIGENCE\backups\`)과 SHA-256이 일치. DB·볼륨은 D:, 백업 사본은 C:와 G:에 있어 서로 다른 디스크입니다.
- [x] **§6 크래시 원인** — 크래시 시각(2026-10-04 18:00~10-05 08:00) Windows System 로그에 디스크·USB·Hyper-V·Kernel-Power 41 이벤트가 없고 PC도 재부팅되지 않았습니다(USB 리셋·디스크 I/O 배제). 72시간 컨테이너 로그와 WSL dmesg에 OOM 흔적도 없습니다. 원인 후보는 문서화된 `AEC-WSL-Reclaim`의 `drop_caches` × 체크포인트 상호작용이며, 완화(`sync` 제거·dirty 64 MB 초과 스킵·120분 간격, `shared_buffers=512MB`, `max_wal_size=512MB`, `wal_compression=lz4`, `stop_grace_period=10m`)가 현재 소스에 들어 있음을 확인했습니다. 정확한 종료 코드 2 송신 주체만 미확정으로 남습니다.
- [x] **§7 WSL 메모리 상한** — `.wslconfig`의 `memory=6GB` 적용 확인, 실제 VM `MemTotal` 6,066,828 kB.
- [x] **§11 Sion 로컬 실행·Drive export** — API 실행 중(`/health` → `{"status":"ok","version":"0.3.0","database":"sqlite"}`), 저장소(`SION_STORAGE_ROOT`)에 스냅샷·그래프가 계속 갱신(03:54 KST), 라이브 DB는 `D:\SionData\sion.db`로 Drive 바깥입니다. `AutoSync_Code_To_GDrive` 작업은 존재하지 않아 라이브 DB가 Drive로 복사되지 않습니다.
- [ ] **오너 몫(에이전트 불가)** — §4 방화벽: 현재 18080·22217은 리스닝 중이 아니어서 지금은 LAN 노출이 없고 차단 규칙도 아직 없습니다. 해당 컨테이너를 다시 띄우기 전에 **관리자 PowerShell**에서 `C:\CODE\_ops\grokbot-firewall.ps1`을 실행해야 합니다(에이전트는 UAC를 우회하지 않습니다).
- [ ] **오너 판단** — §8 `/review` 221건(자동 승인 없음), §9/§10 외부 저장소 갱신(AGENTS.md상 이 저장소에서 건드리지 않음), §12 정리(오너 확인 후 삭제).

## 끝나면

- `docs/STATUS.md` / `docs/STATUS.ko.md` 의 "남은 작업"과 이슈 #33을 갱신하는 PR을 올립니다(개인정보 검사 후).
- 이 파일의 체크 표시와 결과 요약도 같은 PR에 넣습니다. 비밀값·PC 이름·사용자 경로는 넣지 않습니다.
