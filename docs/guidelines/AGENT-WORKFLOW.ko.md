# 에이전트 작업 지침 (Sion 모노레포 + 연결 저장소)

작성: 2026-10-08 (Asia/Seoul). 이번 주(모노레포 통합, 보관 저장소 PR 이식, 병렬 스프린트, 운영 PC 전환 준비)에서
실제로 겪은 문제를 규칙으로 정리했습니다. 사람·에이전트 모두 적용합니다. 상위 규칙은 루트 [`AGENTS.md`](../../AGENTS.md)입니다.

---

## 1. 어디를 고치는가: 모노레포 vs 연결(브릿지) 저장소

| 구분 | 저장소/경로 | 규칙 |
|---|---|---|
| **모노레포** | `khs0927/Ontology-platform` — `packages/regulation`(ArchOntos), `packages/aec`(Ontology), `packages/cad/god-cad`(GOD-CAD) | 코드 수정은 여기서. 원본 저장소(ArchOntos, Ontology, GOD-CAD, CAD-MCP)는 **보관(읽기 전용)** |
| **브릿지** | power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad | 각자 저장소에서 각자 PR. 모노레포에서 이들 코드를 고치지 않음 |
| **연결 방식** | `docs/INTEGRATION_CONTRACTS.md`, `sion_core.contracts` | 버전된 JSON 스키마 + 고정 커밋 + 계약 테스트. 상류 계약이 바뀌면 **스키마·고정 커밋·계약 테스트를 한 PR에서** 갱신 |

- Sion은 CAD를 **직접 수정하지 않습니다**. 브릿지에서 온 데이터는 근거(evidence)·요청 범위 사실일 뿐 정본 상태가 아닙니다.
- DXF 읽기는 모두 `sion_cad.reader` 를 거칩니다.

## 2. subtree 규칙

- git subtree는 **세 디렉터리뿐**입니다: `packages/regulation`(ArchOntos), `packages/aec`(Ontology),
  `packages/cad/god-cad`(GOD-CAD) — 루트 [`AGENTS.md`](../../AGENTS.md)의 Integration 절과 같습니다.
  `packages/core`, `packages/ingestion`, `packages/graphrag` 등 나머지 `packages/*` 는 **일반 패키지**이고 subtree가 아닙니다.
- **subtree 병합(`git subtree pull/merge` 커밋)이 들어간 브랜치는 rebase 하지 않습니다**(히스토리가 깨짐).
  그런 브랜치에서 최신 main을 받을 때는 `git merge origin/main`. 일반 패키지만 고친 브랜치에는 이 제한이 없습니다.
- 세 subtree 패키지는 각자의 테스트·CI(`aec.yml`, `regulation.yml`, GOD-CAD 테스트)를 계속 초록으로 유지합니다.
- 히스토리 재작성(개인정보 정리 등)은 오너 승인 + 로컬 복구 백업 + `--force-with-lease=<ref>:<expected>` 로만. 평소에는 **force push 금지**.

## 3. 보관 저장소의 PR을 모노레포로 이식하기

보관된 저장소에는 더 이상 병합할 수 없습니다. 쓸모 있는 PR만 골라 옮깁니다.

1. **diff를 읽는다.** 제목만 보고 옮기지 않습니다. 이미 main에 들어간 내용이 있는지 확인(예: Ontology #86은 #90에 포함돼 따로 안 옮김).
2. **경로를 고친다.** `src/...` → `packages/aec/src/...` 처럼 패키지 경로로. import·스크립트 경로·문서 링크·CI 경로 필터도 함께.
3. **사적 메모는 버린다.** `PROGRESS.md`, 작업 로그, 개인 경로·PC 이름·이메일이 들어간 파일·주석은 옮기지 않습니다.
4. **안전한 기본값(fail-closed).** 권한·네트워크·외부 호출 관련 코드는 설정이 없거나 애매하면 **거부**하도록 옮깁니다.
5. **PR 본문에 출처를 적는다.** "archived Ontology#80 이식", 뺀 것과 그 이유, 원본 PR에 남길 코멘트(보관 전이라면).
6. 모노레포 루트 테스트 + 해당 패키지 테스트 둘 다 통과시킨 뒤 병합.

## 4. 병렬 스프린트 프로토콜

| 항목 | 규칙 |
|---|---|
| 작업 공간 | 작업자(에이전트)마다 **자기 클론**(예: `/workspace/<sprint>/<worker>/`). 다른 작업자의 디렉터리·브랜치를 건드리지 않음 |
| 브랜치 | `sprint/…`, `sprint2/…` 처럼 스프린트 접두사 + 주제. 한 브랜치 = 한 주제 |
| 범위 | 맡은 파일만 고침. diff가 범위를 벗어나면 PR을 나눔. 공용 파일은 **소유자 한 명**(예: `docs/STATUS.md`, `docs/STATUS.ko.md`는 문서 담당만) |
| 병합 | **CI 전부 초록 확인 후** `gh pr merge --merge --delete-branch` (저장소 공통 관례로 merge commit 사용. squash·rebase 병합이 **반드시 금지**되는 것은 위 세 subtree 경로의 subtree 병합이 들어간 PR) |
| 충돌 | 나중에 병합하는 쪽이 `git merge origin/main` 으로 해결. rebase·force push 금지 |
| 요청량 제한 | 한 번에 다 띄우지 않음. **4–5개씩 묶어서** 실행, 우선순위 높은 것부터. 멈춘 작업은 범위를 줄여 다시 시작 |
| 기록 | 마지막에 STATUS 담당이 병합된 PR을 **다시 조회**해서 상태 문서를 실제와 맞춤(“진행 중”으로 남은 항목이 없게) |
| 보고 | 짧게: 무엇을, 어느 PR로, 무엇이 남았는지. 실패·건너뛴 것도 숨기지 않음 |

## 5. 공개 저장소 개인정보 규칙

Ontology-platform은 **PUBLIC** 입니다.

- 커밋 신원: GitHub noreply 주소만 사용 (`git config user.email <GitHub 사용자명>@users.noreply.github.com`).
- 커밋·PR 전에 반드시:
  ```bash
  python scripts/check_public_privacy.py
  ```
- 넣지 말 것: 개인 이메일, 사용자 홈 경로(드라이브\사용자 폴더\이름 형태 → `<USER_HOME>` 또는 `$env:USERPROFILE`/`%USERPROFILE%`),
  사용자 PC 이름(→ “메인 PC”, “보조 PC”), Google Drive 파일·폴더 ID, 토큰·`.env` 값, 대화 기록, 비공개 도면 데이터.
- PR 본문·코멘트·커밋 메시지에도 같은 규칙. 로그를 붙일 때는 경로·호스트명을 가리고 붙입니다.

## 6. 보안 기본값

- **인증:** 기본 `local-only`. 모든 POST는 `write:knowledge` 필요. 원격 모드(`bearer`, `local-or-bearer`)는
  실제 토큰 + `SION_INGEST_ROOTS` 설정이 있어야 켜짐. 토큰 비교는 상수 시간.
- **netguard(fake-IP 규칙):** Clash 등 fake-IP DNS 프록시는 외부 호스트를 `198.18.0.0/15` 로 돌려줍니다.
  이 대역은 **로컬이 아님**으로 취급해야 합니다(PR #40). 로컬 판정은 loopback 등 명확한 경우만, 애매하면 외부로 보고 차단.
  LLM·임베딩 호출은 기본 로컬(Ollama 등)만 허용합니다.
- **토큰 출력 금지:** `.env` 값은 변수에만 읽어 쓰고 `Write-Host`·로그·PR에 출력하지 않습니다. 연결 문자열은 비밀번호를 가리고 출력.
- **CORS:** 허용 목록(`AEC_CORS_ORIGINS` 등)만. 와일드카드 금지.
- **수집 경로:** 지정된 루트(`SION_INGEST_ROOTS`, AEC import roots) 밖은 거부.
- 새 외부 코드는 라이선스·테스트를 확인하고 들입니다.

## 7. PC 운영 규칙

- **드라이런이 기본.** 운영 스크립트는 인자 없이 돌리면 계획만 출력하고, `-Apply` 를 붙여야 바뀌게 만듭니다(예: `switch-to-monorepo.ps1`).
- **바꾸기 전에 백업.** 예약작업은 `Export-ScheduledTask` 로 XML 백업, 설정 파일(`.env`, `.wslconfig`, MCP 설정)은 `*.bak-<시각>` 사본.
- **DB 볼륨을 다시 초기화하지 않음.** compose 프로젝트 이름이 바뀌면 `<project>_aec-pgdata` 가 새로 만들어집니다.
  기존 프로젝트명을 감지해 `-p`/`COMPOSE_PROJECT_NAME` 으로 고정하고, 전환 후 같은 볼륨인지 다시 검사합니다.
  `docker compose down -v`, 볼륨 삭제, `init` 재실행 금지. 마이그레이션은 멱등(`init-db`)만.
- **라이브 DB 파일을 복사·동기화하지 않음.** 백업은 `pg_dump` 덤프로만. Drive로는 덤프·스냅샷만. DB와 백업은 **다른 디스크**에.
- **긴 작업은 예약작업으로.** 수 시간짜리 수집·재색인은 대화형 세션에서 붙잡지 말고 `\AEC\` 예약작업(비관리자, 로그온 트리거,
  뮤텍스로 중복 방지, 재시도·대기 내장)으로 돌리고, 에이전트는 상태만 확인합니다.
- **워커 정지/재개는 드레인으로.** `stop-workers.ps1 -Drain`(돌던 작업은 끝까지) → 변경 → `-Resume`.
- **UAC를 우회하지 않음.** 관리자 권한이 필요한 단계(방화벽 등)는 스크립트를 준비해 두고 오너가 직접 실행.
- **오너 파일 보호.** 오너의 기능 브랜치·로컬 수정은 건드리지 않고 `git worktree add <경로> origin/main` 으로 별도 작업.
  삭제는 목록을 보여 주고 오너가 확인한 것만.
- 권한(PC 제어, CLI 설치, gh 계정)은 **허락받은 세션 안에서만** 씁니다.

## 8. 작업 흐름 요약 (체크리스트)

1. 자기 클론 + `sprint…/주제` 브랜치 + noreply 신원.
2. 범위 안에서 수정 → 패키지 테스트 + 루트 테스트 → `python scripts/check_public_privacy.py`.
3. PR(출처·뺀 것·검증 결과) → CI 전부 초록 → `gh pr merge --merge --delete-branch`.
4. STATUS 담당에게 결과 전달(또는 본인이 담당이면 병합 PR 재조회 후 STATUS 갱신).
5. 운영 PC가 필요한 일은 [`docs/ops/MAIN-PC-TODO.ko.md`](../ops/MAIN-PC-TODO.ko.md)에 순서·명령·성공 기준·롤백과 함께 남김.
