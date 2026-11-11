# 작업 완수 프레임워크 (Completion Playbook)

이 저장소에서 "중단된 작업"이 다시 유실되지 않도록, 사람과 에이전트가 모두 따르는 표준 절차다.
2026-11-11/12의 머지 파도(#106~#133)에서 검증된 방식을 문서화한 것이다.

- **상태(지금 어디까지 왔나)**는 [`docs/STATUS.md`](../STATUS.md) / [`docs/STATUS.ko.md`](../STATUS.ko.md)가 유일한 기록이다. 이 문서는 절차만 정의하고 현재 상태를 복사하지 않는다.
- 저장소 기본 규칙(개인정보 금지, noreply 커밋, Drive 동기화 금지 등)은 루트 [`AGENTS.md`](../../AGENTS.md)가 우선한다.

## 0. 원칙

1. **Git/GitHub가 유일한 기준이다.** 로컬 파일이나 대화 기록이 아니라 원격 저장소가 참이다.
2. **병합은 검사 초록불 이후에만.** 체크가 전부 완료되고 실패가 0일 때만 머지한다.
   예외는 인프라 플레이크뿐이며(§3), 그 경우에도 판단 근거를 PR 코멘트로 남긴다.
3. **충돌은 유니온으로 푼다.** 양쪽 의도를 모두 보존하고(기능·테스트 삭제 금지), 중복
   정의/중복 판정만 제거한다. 해결 원칙은 커밋 메시지와 PR 코멘트에 기록한다.
4. **오너 결정은 대신하지 않는다.** §5 목록은 에이전트가 임의로 진행하지 않는다.
5. **공개 전 프라이버시 검사.** 푸시 전 `python scripts/check_public_privacy.py` 0건.

## 1. 파이프라인

```
intake → triage → verify → green-gate merge → (release) → hygiene → handoff
```

### 1) Intake — 열린 작업 목록 만들기

```bash
gh pr list --state open --json number,title,isDraft,mergeStateStatus,headRefName
gh issue list --state open --limit 40
gh run list --branch main --limit 10        # main 자체가 깨졌는지 먼저 확인
```

각 항목을 네 부류로 분류한다.

| 분류 | 뜻 | 다음 행동 |
|---|---|---|
| A. 검증 가능 | 최신 base, 충돌 없음 | §2 검증 후 머지 |
| B. 리베이스 필요 | base가 뒤처짐/충돌(DIRTY) | main 병합 → 충돌 유니온 해결 → 재검증 |
| C. 오너 결정 필요 | §5 목록에 해당 | 코멘트로 상태 정리 후 보류 |
| D. 인프라 플레이크 | 코드와 무관한 실패 | 재시도하거나 §3 완화책 적용 |

main 자체가 빨간이면 **모든 PR 작업보다 먼저** main을 고친다(대부분 최근 머지가 원인).

### 2) Triage — 머지 순서 정하기

- 파일 겹침이 적은 PR부터 머지한다. 겹치는 PR끼리는 하나를 머지한 뒤 나머지 브랜치에
  main을 병합해 갱신하고 CI를 다시 돌린다. (예: #125 머지 후 #126 갱신)
- 드래프트는 준비되면 `gh pr ready`로 변환할 수 있지만, 변환 여부는 작성자 의도를 존중한다.

### 3) Verify — 로컬 검증

- `python scripts/check_public_privacy.py` → 0건.
- 워크플로 변경: `python -c "import yaml; yaml.safe_load(open(...))"`로 YAML 파싱.
- 코드 변경: 관련 초점 테스트(예: `python -m pytest -q tests/test_<관심사>.py`).
  전체 테스트는 CI가 담당하므로, 로컬에서는 "변경이 무엇을 깨는지"만 빠르게 확인한다.

### 4) Green-gate merge

```bash
gh pr checks <n>          # 전부 완료 + 실패 0 확인
gh pr merge <n> --squash --delete-branch
```

- 머지 방식은 스쿼시가 기본(히스토리에 PR당 1커밋). 서브트리 병합 등 특수 케이스는
  기존 관례를 따른다.
- 머지 직후 `git fetch origin main`으로 main이 예상대로 움직였는지 확인한다.

### 5) Release

1. 준비 PR: `pyproject.toml` 버전 bump + `uv.lock` 재생성 + `CHANGELOG.md` +
   `docs/releases/vX.Y.z.md`. CI 초록 확인 후 머지.
2. 태그는 **릴리즈 노트가 설명하는 코드 상태의 커밋**에 찍는다:
   `git tag -a vX.Y.Z <sha> && git push origin vX.Y.Z`
3. `gh release create vX.Y.Z --title ... --notes-file ...` — 노트는
   `docs/releases/vX.Y.z.md`에서 "상태/미생성" 문구를 제거해 만든다.
4. 태그/배포는 §5의 오너 결정 사항이다. 준비 PR만으로 세션을 끝내도 괜찮다.

### 6) Hygiene — 브랜치 정리

- 삭제 조건(전부 충족): tip이 `origin/main`에 완전 포함(`git merge-base --is-ancestor`)
  + 열린/드래프트 PR 헤드가 아님 + `main`/`release/*`/`gh-pages` 제외 + 최근 3일 내 갱신 아님.
- 고유 커밋이 남은 브랜치는 **삭제하지 않고** 오너 검토 목록에 남긴다.
- 삭제 리포트는 `docs/ops/BRANCH-CLEANUP-<날짜>.md`로 남긴다(브랜치명+구 tip SHA, 복구 경로 포함).

### 7) Handoff — 세션을 끝내기 전

`docs/STATUS.md`와 `docs/STATUS.ko.md`의 "현재 상태"를 갱신한다: 기준 커밋, 머지 파도
기록, 열린 PR, 오너 결정 대기 목록. **이 갱신이 다음 세션(사람·에이전트)의 시작점이다.**
상태 문서가 stale하면 그 자체가 중단된 작업이다.

## 2. 병렬 에이전트 운영 규칙

- 공유 체크아웃(`Ontology-platform/`)은 **읽기 전용**으로 취급한다. 에이전트마다 자기
  클론(예: `.work/<이름>`)에서만 쓰고, 클론의 `origin`은 반드시 GitHub URL로 재설정한다.
- 파일 스코프를 겹치지 않게 나누고(작업 지시에 명시), 한 파일을 두 에이전트가 고치지
  않게 한다. 머지 권한은 리드(lead)만 가진다.
- force-push는 기본 금지. 예외: 병합 커밋으로 갱신하면 필요 없다.
- CI 대기(10분 이상)는 폴링 루프로 턴을 막지 말고 백그라운드 잡 또는 짧은 폴링을 쓴다.
- 서브에이전트에게는 "무엇을, 어디서, 어떻게 검증하고, 끝나면 무엇을 보고할지"를
  한 번에 적어준다. 중간 출력은 크게 쌓지 않도록 요약을 요구한다.

## 3. 알려진 인프라 플레이크와 완화책

| 증상 | 원인 | 완화 |
|---|---|---|
| `Verify`의 PostgreSQL 마이그레이션 잡이 `Temporary failure resolving 'archive.ubuntu.com'`로 실패 | 러너의 apt 미러 DNS 간헐 실패 | **해결됨(#128)**: apt 대신 Postgres 서비스 컨테이너 안의 psql/pg_isready/pg_dump를 `docker exec`으로 사용 |
| AEC 운영 스택 잡의 apt 설치가 느리거나 실패 | 같은 DNS 문제 | **완화됨(#130)**: bounded retry + `Acquire::Retries/Timeout` |
| CI가 전부 `queued`로 오래 머묾 | 동시 실행 한도 포화(여러 PR × 잡 17개) | 기다리거나 머지를 진행해 열린 PR 수를 줄인다. 실패가 아니므로 재시도 불필요 |

플레이크로 판명된 실패는 재실행(`gh run rerun <runId> --failed`)으로도 해결된다. 재실행으로도
같은 자리에서 반복 실패하면 플레이크가 아니니 코드를 의심한다.

## 4. 체크리스트 (짧은 버전)

- [ ] `gh run list --branch main` — main 초록?
- [ ] 열린 PR/이슈 목록 → A/B/C/D 분류
- [ ] B는 main 병합 + 유니온 해결 → 로컬 초점 테스트 → push
- [ ] 체크 전부 완료·실패 0 → 스쿼시 머지
- [ ] 푸시 전 `check_public_privacy.py` 0건, 커밋은 noreply 신원
- [ ] 릴리즈 준비는 PR로, 태그는 오너 승인 하에
- [ ] main 완전 포함 브랜치 삭제 + 리포트
- [ ] `docs/STATUS.md` / `STATUS.ko.md` 갱신 (handoff)

## 5. 오너 결정 목록 (에이전트 금지)

1. **릴리즈 태그/배포** — 준비가 끝나도 태그 생성은 오너가 명시 요청할 때만. (v0.3.0은
   2026-11-12 오너 요청으로 생성됨)
2. **#109 NVIDIA 페더레이션 머지와 라이브 검증** — NVIDIA 자격 증명이 필요한 검증이
   포함되어 있어 환경이 있는 곳에서 판단해야 한다.
3. **메인 PC 전환 `-Apply` 실행** — 실제 Windows 예약 작업을 바꾼다. 드라이런(읽기 전용)은
   가능하나 `-Apply`는 [`docs/ops/MAIN-PC-TODO.ko.md`](MAIN-PC-TODO.ko.md) 절차대로 오너가 실행.
4. **GraphRAG 리프레시** — 런타임 전환 이후에만 의미가 있다.
5. **`/review` 승인·반려** — 자동 승인은 없다. 221 대기 후보(214 SketchUp 분류 + 7 맵
   엣지)는 오너가 판단한다.
6. **HS-CAD 유출 키 폐기 확인**(MAIN-PC-TODO 최상단) — 오너만 할 수 있는 계정 작업.
