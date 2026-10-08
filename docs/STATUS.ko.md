# Sion Ontology Platform — 현재 상태 (한국어 요약)

갱신: 2026-10-08 22:00 KST (Asia/Seoul)

## 아키텍처 (요약)

1. **메인 모노레포** `khs0927/Ontology-platform` (v0.2.0). GitHub가 코드 이력의 기준이다.
2. **병합된 패키지**: `packages/regulation`(ArchOntos), `packages/aec`(Ontology/`aec_intelligence`), `packages/cad/god-cad`(GOD-CAD). 원본 저장소는 보관(읽기 전용).
3. **브릿지 전용(별도 저장소)**: power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad, CAD-MCP. 버전된 JSON 계약 + 계약 테스트로만 연결. Sion은 CAD를 직접 수정하지 않는다.
4. **런타임 DB**: 로컬 PostgreSQL(또는 SQLite 스모크). `public` + `regulation` 스키마. 라이브 DB는 디스크에 두고, 커밋된 쓰기마다 `SION_STORAGE_ROOT`(Drive 데스크톱 폴더)로 스냅샷·그래프를 export한다.
5. **수집**: 문서(PDF/DOCX/md…), DXF(`sion_cad.reader`), IFC, 에이전트 세션 브릿지(Antigravity/Codex/Claude + DeepSeek/Hermes/ZCode 로컬 로그 리더).
6. **관계·리뷰**: 31노드/43관계는 `unverified` 후보로 적재. `/review`에서 사람이 승인·반려. SketchUp 0914 지식팩(노드 1,195 / 관계 4,509)도 후보·검증 혼합.
7. **GraphRAG / 검색**: LightRAG 경계, 임베딩·벡터 검색, AEC/CAIR 읽기 전용 페더레이션. 쓰기는 `write:knowledge` 스코프.
8. **CI**: Tests(Ubuntu+Windows), Verify, AEC/CAD, Regulation, Public security. agent-bridge Windows exe는 Releases.

## 현재 상태 (2026-10-08 22:00 KST 재확인)

기준: `main` `e2bffe3`(#48), 커밋 316개. 열린 PR은 이 PR뿐, 열린 이슈는 #3·#33.

**테스트** (지금 숫자. 아래 예전 절의 숫자는 그 시점 기록)

| 범위 | 설치 | 결과 |
|---|---|---|
| 루트 `tests/` | `.[all,test,dev]` | **265 통과, 3 건너뜀** (3개는 `SION_TEST_POSTGRES_URL` 필요) |
| 루트 `tests/` | 최소 `.[test]` | 239 통과, 29 건너뜀 (선택 라이브러리 없음) |
| `packages/aec` | | 619 통과, 51 건너뜀 |
| `packages/regulation` | 로컬, PostgreSQL 없음 | 213 통과, 39 건너뜀 (PostgreSQL 테스트는 CI에서 실행) |
| `packages/cad/god-cad` | | 27 통과 |

**CI:** `main`의 체크 15개 모두 통과 (GitHub Actions 14개 + CircleCI 1개). 목록은 `docs/STATUS.md` "Current state".

**히스토리 재작성 2회** (둘 다 오너 승인, force push)
1. **2026-10-08 03:11 KST — exe 제거.** `git filter-repo`로 `bin/sion-agent-bridge.exe`를 모든 히스토리에서 제거(팩 75.7 MiB → 2.6 MiB). exe는 Release v0.2.0에 있음.
2. **2026-10-08 12:23 KST — 개인정보 정리.** 공개 히스토리의 이메일, Google Drive 파일 ID, 장치명을 가림. `main`과 다른 브랜치 29개(총 30개 ref)를 같은 초(12:23:55)에 force push. 이전 `main` `217ccd3` → 새 `54e1921`("Protect public privacy and local HTTP access"가 맨 위에 추가). 이전 main의 커밋 263개는 제목·작성 시각 그대로 모두 남아 있고, 트리 차이는 가린 파일 9개뿐. 사라진 커밋 없음.

영향:
- 12:23 이전에 만든 클론은 모두 **예전 히스토리**라 `origin/main`과 갈라져 `git pull --ff-only`가 실패합니다. 백업 후 `git fetch` + `git reset --hard origin/main`, 또는 새로 클론하세요(`docs/ops/MAIN-PC-TODO.ko.md` 1단계). **예전 클론·예전 로컬 브랜치에서는 절대 푸시하지 마세요.** 지운 exe와 가리기 전 정보가 다시 올라갑니다. 새 히스토리인지는 `git merge-base --is-ancestor 54e1921 HEAD`로 확인합니다.
- 재작성된 커밋은 GitHub "Verified" 서명 표시가 사라졌습니다.

**브랜치 정리 (22:00 KST):** `main`에 완전히 포함된(고유 커밋 0, 열린 PR 없음) 원격 브랜치 13개를 저장소 밖 번들로 백업한 뒤 삭제했습니다. 고유 커밋이 남은 오래된 브랜치 19개는 **그대로 두었습니다**(오너 판단). 목록은 `docs/STATUS.md` "Branch cleanup".

## 2026-10-08 저녁 스프린트 결과 (20:30 재확인)

**Ontology-platform 병합** (모두 CI 통과 후 병합)
- [#37](https://github.com/khs0927/Ontology-platform/pull/37) 보관된 Ontology #86/#90/#91 이식 — 읽기 전용 브리지 fail-closed 계약 + 근거 수명주기.
- [#38](https://github.com/khs0927/Ontology-platform/pull/38) 보관된 Ontology #80 이식 — RAM 부족·원본 폴더 없음에도 워커가 죽지 않고 대기·재시도, 속도/ETA 계산 수정.
- [#39](https://github.com/khs0927/Ontology-platform/pull/39) `switch-to-monorepo.ps1` + 한국어 런북 — 기본 드라이런, `-Apply`로 실행, DB 볼륨이 바뀌면 거부.
- [#40](https://github.com/khs0927/Ontology-platform/pull/40) netguard가 fake-IP 대역 `198.18.0.0/15`를 로컬로 오인하던 보안 문제 수정.
- [#41](https://github.com/khs0927/Ontology-platform/pull/41) 상태 문서 + 이 한국어 요약.
- #34·#35는 #36(Windows pytest)로 대체되어 19:45에 닫음.

**연결 저장소 병합** (각 저장소에서 진행)
- power-cad-mcp #42(철골 플레이북), #40(문서 동기화), #43(`cad_hs_*` 자산 도구 10개, 전체 65개, `..` 경로 탈출 수정).
- hs-steel-cad #7 자산 레지스트리(819개, Windows 줄바꿈 해시 문제 수정).
- korean-land-mcp #1 CI 추가(테스트 29개). HS-CAD #157. All-In-Cad 테스트 96개 통과(병합 없음), 브랜치 `agent/autocad-host-2027`에 `edba1f9`(PureWindowsPath 테스트 수정, CI 통과) 푸시 — PR 없음. zium-onboarding #1 병합(`bacdf61`, lockfile 재동기화·lint 오류 0), 템플릿 테스트 실패 11개 남음.

**후속 스프린트(sprint2/) 병합**
- [#42](https://github.com/khs0927/Ontology-platform/pull/42) 연결 저장소 계약을 10/8 저녁 최신 커밋으로 재고정, 계약 테스트 58 → 81개, `hs-steel-section-catalog/1` 스키마 추가.
- [#44](https://github.com/khs0927/Ontology-platform/pull/44) 일괄 판정 API `POST /api/v1/relations/candidates/bulk` + 한국어 `/review` 일괄 화면(필터·단축키·표시 전용 추천 힌트, 자동 승인 없음).
- [#45](https://github.com/khs0927/Ontology-platform/pull/45) 테스트 의존성 httpx2, `uv.lock` 알려진 취약점 0.
- [#46](https://github.com/khs0927/Ontology-platform/pull/46) 보관된 Ontology #88 headless 도면 컨텍스트 테스트 이식(경로 구분자 무관 검사, ubuntu/macos/windows 워크플로 `aec-drawing-context-headless.yml`). #89는 `packages/aec/docs/verification-boundary.md`로, #83/#84/#87은 보관 상태 전용이라 제외.
- [#47](https://github.com/khs0927/Ontology-platform/pull/47) `verify.yml`에 백업/복원 스모크 테스트(PG17 + pgvector, 행 수·확장 버전·미적용 마이그레이션 없음) — 이슈 #1 닫음(`scripts/verify-postgres.sh`가 담당).
- 이슈 #2는 export-on-write(`docs/STORAGE.md`, `drive_export.py`)로 대체되어 닫음. 열린 이슈는 #3(31노드·43관계 오너 검토 대기)과 #33뿐.
- korean-land-mcp #2 npm audit 20 → 2건. HS-CAD #158 Pillow ≥ 12.3, `opencode.json`은 커밋된 키 대신 `{env:GOOGLE_GENERATIVE_AI_API_KEY}` 사용.
- power-cad-mcp #44 `FakeTimeProvider`로 `OntologyAskTests` 결정적 테스트화(Windows 타이밍 간헐 실패 해결).

**20:30 기준 열림:** power-cad-mcp #45(HS-STEEL 스킬)·#49·#46(CAD 없는 자산 수집 + Graph RAG 인덱스)·#47(headless DXF)·#48(`cad_hs_search`/`cad_hs_index_status`).
보관된 Ontology #88 headless 테스트 이식은 다시 하기 전에 열린 PR 확인. HS-CAD PR 분류 완료: 32개 닫음(이미 main에 포함), 병합 0, 34개 열림(한국어 코멘트). xiCAD `mcp==1.28.1` 고정은 Python 3.13에서 깨짐.

**새 문서**
- [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) — 메인 PC 복귀 시 순서대로 실행할 체크리스트(명령·성공 기준·롤백).
- [`docs/guidelines/AGENT-WORKFLOW.ko.md`](guidelines/AGENT-WORKFLOW.ko.md) — 이번 주 작업에서 정리한 에이전트 작업 지침.

## 소유자(오너) 할 일

0. **최우선(어느 PC든):** HS-CAD `opencode.json`에 커밋됐던 Google AI Studio API 키 교체(2026-05-21부터 공개 히스토리, main은 #158로 환경변수 사용) → HS-CAD 비밀 스캔 알림 #1을 "Revoked"로 닫기. 선택: power-cad-mcp·hs-steel-cad·All-In-Cad에 Dependabot + 비밀 스캔 켜기. 자세한 절차는 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 맨 위.
0b. HS-CAD PR 판단: 분석 체인 2개(#23/#25/#27/#29/#32/#34/#35, #24/#26/#28/#30/#31/#33/#37) main 포함 확인 후 닫기, #1/#4/#5/#7은 필요한 모듈만 새 PR로 이식, #12는 현재 `main.py` 기준 재작성, 실기 실행은 Windows + ZWCAD PC 필요. 자세한 내용은 to-do 문서의 HS-CAD 절.
0c. All-In-Cad 브랜치 `agent/autocad-host-2027`(`edba1f9`, CI 통과)을 PR로 올려 병합할지 결정. zium-onboarding 템플릿 테스트 실패 11개 수정.
1. `/review`에서 맵 후보 43건 + SketchUp 분류 214건·워크플로 링크 승인/반려 (이슈 #3, #33).
2. 메인 PC 온라인 시 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 실행 — 보관된 Ontology 체크아웃 → `packages/aec` 전환(`switch-to-monorepo.ps1` 드라이런 후 `-Apply`).
3. `AutoSync_Code_To_GDrive` 예약작업 비활성화 확인 (라이브 DB 복사 금지).
4. 전환 후 GraphRAG 재색인(FAILED 커뮤니티 6건 재시도).
5. 운영 방화벽 스크립트 관리자 실행(18080/22217), DB 덤프를 DB와 다른 디스크로 복사.
6. SketchUp 덤프 경로(`skp_path`) 보존 여부 결정.
7. 12:23 이전에 만든 PC의 예전 체크아웃을 새 히스토리로 맞추거나 보관(백업 후 `fetch` + `reset --hard origin/main`). 그 전에는 거기서 푸시 금지.
8. 고유 커밋이 남은 오래된 원격 브랜치 19개를 남길지 정리할지 결정.
