# Sion Ontology Platform — 현재 상태 (한국어 요약)

갱신: 2026-11-12 04:00 KST (Asia/Seoul). `origin/main` `d972785`(태그 `v0.3.0`)를 기준으로 다시 확인했다.

## 아키텍처 (요약)

1. **메인 모노레포** `khs0927/Ontology-platform`. 릴리스 태그는 [v0.3.0](https://github.com/khs0927/Ontology-platform/releases/tag/v0.3.0)(2026-11-12)이다. GitHub가 코드 이력의 기준이다.
2. **패키지**: `packages/aec`(Ontology/`aec_intelligence`), `packages/cad/god-cad`(GOD-CAD)는 서브트리로 들어와 있다. ArchOntos는 [#119](https://github.com/khs0927/Ontology-platform/pull/119)(2026-11-10)부터 `regulation` extra의 고정 의존성이다. 핀은 `534367c`(ArchOntos #22). 수정은 ArchOntos 저장소에서 하고, 여기에는 핀만 올린다.
3. **브릿지 전용(별도 저장소)**: power-cad-mcp, hs-steel-cad, korean-land-mcp, All-In-Cad, CAD-MCP (HS-CAD는 2026-11-03 사용 중단). 버전된 JSON 계약 + 계약 테스트로만 연결. Sion은 CAD를 직접 수정하지 않는다.
4. **런타임 DB**: 로컬 PostgreSQL(또는 SQLite 스모크). `public` + `regulation` 스키마. 라이브 DB는 디스크에 두고, 커밋된 쓰기마다 `SION_STORAGE_ROOT`(Drive 데스크톱 폴더)로 스냅샷·그래프를 export한다.
5. **수집**: 문서(PDF/DOCX/md…), DXF(`sion_cad.reader`), IFC, 에이전트 세션 브릿지(Antigravity/Codex/Claude + DeepSeek/Hermes/ZCode 로컬 로그 리더).
6. **관계·리뷰**: 31노드/43관계는 `unverified` 후보로 적재. `/review`에서 사람이 승인·반려. SketchUp 0914 지식팩(노드 1,195 / 관계 4,509)도 후보·검증 혼합. 자동 승인은 없다.
7. **GraphRAG / 검색**: LightRAG 경계, 임베딩·벡터 검색(`sion_embedhub`는 #106, 2026-11-11 병합), AEC/CAIR 읽기 전용 페더레이션. 쓰기는 `write:knowledge` 스코프.
8. **CI**: Tests(Ubuntu+Windows, uv.lock), Verify, AEC/CAD, Regulation(ArchOntos 핀·가드·브리지·마이그레이션), Public security, CircleCI pytest. agent-bridge Windows exe는 패키지 경로가 바뀔 때 빌드하고, 배포 파일은 Releases에 둔다.

## 현재 상태 (2026-11-12 KST 재확인)

기준: `main` `d972785`(#109 병합, 2026-11-12 03:3x KST)이며 [v0.3.0](https://github.com/khs0927/Ontology-platform/releases/tag/v0.3.0) 태그 라인과 같다. 2026-10-08의 `e2bffe3`(#48)보다 커밋 259개가 앞에 있고, 전체 이력은 578커밋이다. 2026-11-11 밤부터 11-12 새벽 사이에 #106~#108, #112, #118, #115, #113, #101, #120, #122, #123, #125, #129, #130, #133, #121, #126, #131, #124, #132, #128, #135, #136, #109가 모두 병합됐고, 각 병합은 체크 16~20개가 전부 완료·실패 0인 상태에서 이뤄졌다. 충돌이 있던 #124·#126은 main을 병합해 충돌을 합친 뒤 최종 초록을 확인했고, #109는 main 기준으로 리베이스한 뒤 머지했다. **열려 있는 PR은 없다.** 이런 정리 작업의 표준 절차는 [`docs/ops/COMPLETION-PLAYBOOK.ko.md`](ops/COMPLETION-PLAYBOOK.ko.md)에 정리돼 있다.

**10-08 이후 뼈대**
- ArchOntos 기준은 루트 `pyproject.toml`·`uv.lock`·`docs/INTEGRATION_CONTRACTS.md`의 핀(`534367c`)이다. #119에서 `packages/regulation` 아래 복사본은 제거됐다.
- `packages/aec`는 보관된 Ontology와 맞춰 두었다(#110, #114, #116, #117). Google Drive CAD GraphRAG 팩도 main에 있다(`e9bd7eb`).
- **메인 PC 전환은 끝났다.** 2026-11-12 02:21–02:34 KST에 `-Apply`를 끝까지 돌려 작업 XML 백업 → 드레인 → 사전 `pg_dump` → 같은 볼륨으로 db/api 재생성 → 마이그레이션 → venv 확인 → 작업 재등록까지 마쳤다(같은 볼륨 `ontology_aec-pgdata`). 재등록 직후 활성화 판정 버그로 9개 작업이 꺼져 있던 건은 수동 복구했고 [#135](https://github.com/khs0927/Ontology-platform/pull/135)가 고쳤다. 04:00 KST 검증 결과: API·컨테이너 healthy, 관리 작업 9개가 모노레포 경로, 워커가 새 venv에서 동작, GraphRAG 재색인은 **DONE 197 / FAILED 0**(예전 FAILED 6건 소실, 2시간 주기 실행). DB 백업은 `C:\AECBackup`에 해시 동일한 사본이 있고, 2026-10-04 크래시는 `drop_caches`×체크포인트 상호작용으로 좁혀졌으며(호스트 디스크/USB/Hyper-V 이벤트·OOM 흔적 없음) 완화는 현재 소스에 반영돼 있다. 절차는 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md).
- All-In-Cad #17(`agent/autocad-host-2027`)은 2026-10-29에 병합됐고 #18–#22도 병합됐다. 열린 PR은 없다.
- zium-onboarding PR #2는 2026-11-05에 오너가 병합했고 #3–#5도 뒤따라 병합됐다. 남은 PR은 없다.

아래 "2026-10-08 저녁" 절의 테스트 숫자와 "체크 15개"는 그날의 기록이다.

**지금 main에 걸리는 CI**
Tests(pytest, Windows pytest, uv.lock), Verify(SQLite·API, PostgreSQL 마이그레이션), AEC/CAD(lint·테스트, 운영 스택, api 이미지, GOD-CAD Ubuntu·Windows), Regulation(ArchOntos 핀·가드·브리지·마이그레이션), Public security(privacy, dependencies), CircleCI pytest. #106·#107은 이 묶음이 초록인 상태에서 병합됐다. ArchOntos Helm 렌더와 lint·타입 검사는 ArchOntos 저장소 CI에서 돈다.

**열린 PR**
- #108 준비됨(드래프트 아님), main과 충돌 없음, 33커밋 뒤처짐, 2026-11-07 헤드 CI 초록. SketchUp preflight 실패 시 이번 실행이 만든 파일을 되돌린다.
- #118 드래프트, 충돌 없음, #106·#107만큼(7커밋) 뒤처짐, CI 초록. 토지 레이어 오류·스키마 검증 불가면 fail-closed.
- #115 드래프트, 충돌 없음, 31커밋 뒤처짐, CI 초록. SketchUp 모델 불변·로케이터 검사(#79)와 kordoc-evidence/1 계약 테스트(#71).
- #112 드래프트, 충돌 없음, 31커밋 뒤처짐, CI 초록. Ontology와 `packages/aec`의 읽기 전용 드리프트 목록.
- #109 드래프트, 병합은 되나 `official-inference` 실패(나머지 초록), 33커밋 뒤처짐. NVIDIA Auto Ontology 읽기 전용 연동.
- #113 드래프트, 충돌(`gdrive_cad/README.md`, `graphrag/ask.py`, `parsers.py`). 같은 팩은 이미 main에 있다.
- #101 드래프트, 충돌(`pyproject.toml`, `uv.lock`, 삭제된 `packages/regulation/CHANGELOG.md`, `docs/CLOUD_COMPLETION_2026-11-05.md`), 77커밋 뒤처짐. 벤더 트리에 넣던 건축·토지 검토 워크플로.

**열린 이슈**
- #3 31노드/43관계 구조화 반입. **2026-11-12 종료**: 43개 엣지를 모두 판정(승인 36 · 거절 7), 판정 근거는 `data/review/sion-review-decisions-2026-11-12.md`에 기록. #53의 `data/review/sion-map-relation-decisions.json`은 36건 승인·7건 보류 제안이며, 그 사유를 그대로 적용 기록에 옮겼습니다.
- #33 SketchUp/Drive 후속 체크리스트.
- #71 모바일·PC 독립 운영, Kordoc 연동, 검토/쓰기 E2E.
- #79 다른 SketchUp 모델 추가 수집 파이프라인.
- #80 `/review` 승인 결과를 지침 가중치에 반영. #96–#99로 단계가 들어왔으나 이슈는 열려 있다. 자동 승인은 없다.

## 현재 상태 (2026-10-08 22:00 KST 재확인) — 당시 기록

기준: `main` `e2bffe3`(#48), 커밋 316개. 그날 기준으로 열린 PR은 상태 문서 PR뿐이었고, 열린 이슈는 #3·#33이었다.

**테스트** (2026-10-08 측정값)

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

## 2026-10-09 검증 결과 (PR #51 도면번호 추출) — 2026-10-17 정리

**재평가 — 수정 후 완주, 회귀 없음**
- `feat/drawing-number-extraction`(커밋 `2a3a5491`) 기준 20건 중립 평가 전량 재실행: 20/20 케이스, 파싱 오류 0,
  판정 셀 **43/43 통과**(도면번호 14/14, 분류 18/18, 층 11/11). 존재 적중률 100%.
- **측정 범위 주의:** 정답 후보의 *존재 여부*만 센다. 정밀도·재현율·전체 시트 완성도는 측정하지 않는다
  (`semantic_accuracy`/`precision`/`full_set_recall`은 `None` 고정).
- **비교 표기 주의:** 이전 기록의 "층 8/9 → 9/9"와 이번 "층 11/11"은 분모가 다르다(41셀·43셀). 개선으로 표기하지 않는다.
- **provenance 주의:** 당시 평가는 미커밋 parser 작업본 기준이었다. 이후 parser 수정 커밋(`88ef0c8`)이 추가로 병합됐으며,
  병합된 HEAD 기준 재평가 기록은 아직 없다.
- 라벨은 에이전트가 검토한 변환 DXF 기준이며 원본 DWG/래스터 교차 검증은 없다.

**PR 상태(2026-10-17 확인)**
- #51(도면번호 추출)·#52(도면 분석 지침)·#53(관계 판정 36/7)·#54(규정 게이트웨이 계약)·#55·#56 모두 병합 완료.

**RAM**
- 커널 nonpaged 풀이 약 1.8GB로 비정상적으로 크다. poolmon 미설치로 태그 단위 귀속은 불가.
- 사용자 모드가 아니라 커널 풀이 지배적이며, nonpaged 풀은 앱 종료로 회수되지 않고 재부팅으로만 초기화된다.
- 수집 재개 기준(1분 간격 3회 모두 2GB 이상)은 2026-10-17 현재도 미달 → 워커 정지 유지.

## 소유자(오너) 할 일

0. **최우선(어느 PC든):** HS-CAD `opencode.json`에 커밋됐던 Google AI Studio API 키 교체(2026-05-21부터 공개 히스토리, main은 #158로 환경변수 사용) → HS-CAD 비밀 스캔 알림 #1을 "Revoked"로 닫기. 선택: power-cad-mcp·hs-steel-cad·All-In-Cad에 Dependabot + 비밀 스캔 켜기. 자세한 절차는 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 맨 위.
0b. ~~HS-CAD PR 판단~~ — 2026-11-03 제외: HS-CAD 사용 중단, CAD 호스트 연동은 power-cad-mcp만 사용(HS-CAD 계약 제거). 0번 API 키 폐기는 그대로 필요. (이전 내용: 분석 체인 2개(#23/#25/#27/#29/#32/#34/#35, #24/#26/#28/#30/#31/#33/#37) main 포함 확인 후 닫기, #1/#4/#5/#7은 필요한 모듈만 새 PR로 이식, #12는 현재 `main.py` 기준 재작성, 실기 실행은 Windows + ZWCAD PC 필요. 자세한 내용은 to-do 문서의 HS-CAD 절.)
0c. zium-onboarding PR #2(템플릿 테스트 수정, 2026-10-08에 열림, 당시 CI 초록)는 오너가 검토·병합한다. 병합 여부는 이 환경에서 저장소가 보이지 않아 다시 확인하지 못했다. All-In-Cad는 #17(2026-10-29)과 #18–#22가 병합됐고 열린 PR이 없다.
1. ~~`/review` 승인·반려~~ — **2026-11-12 04:3x KST 완료, 대기 0건.** 2026-11-11의 대기 221건(분류 214 + map 7)을 모두 판정했습니다. 분류 214건은 **승인**(단일 대입, `classification.json` + `model_dump.json` + `.skp` sha256 이중 근거, `properties.basis_ko`), map 7건은 #53 위임 교차검토의 보류 사유를 그대로 기록해 **거절**, guideline 링크 844건은 [#137](https://github.com/khs0927/Ontology-platform/pull/137)로 `source_kind=document` 후보가 목록에 보이게 한 뒤 **승인**(가이드 문서 sha256 고정 행 범위, 신뢰도 0.9, 인용 행 원문 대조 완료). 결과는 **승인 1,094 · 거절 7 · 대기 0**이며 이슈 #3은 종료, #33은 갱신했습니다. 기록: [`data/review/sion-review-decisions-2026-11-12.md`](../data/review/sion-review-decisions-2026-11-12.md).
2. 메인 PC가 켜지면 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 2단계를 순서대로 실행한다. `switch-to-monorepo.ps1`를 먼저 드라이런하고, DB 볼륨이 같으면 `-Apply`한다. 2026-10-09 실행은 `\AEC\` 재등록 전에 멈췄으므로 그 항목은 체크하지 않는다. `-SkipVenv`는 쓰지 않는다.
3. `AutoSync_Code_To_GDrive` 예약작업 비활성화 확인 (라이브 DB 복사 금지).
4. 전환 후 GraphRAG 재색인(FAILED 커뮤니티 6건 재시도).
5. 운영 방화벽 스크립트 관리자 실행(18080/22217), DB 덤프를 DB와 다른 디스크로 복사.
6. ~~SketchUp 덤프 경로(`skp_path`) 보존 여부~~ — **2026-11-12 결정: 파일은 바이트 단위로 그대로 둡니다.** 라이브 DB의 증거 행이 해당 파일의 `source_sha256`를 저장하므로, 고치면 근거 사슬이 끊깁니다. 파일 안의 로컬 경로는 출처 표기일 뿐이며 공개 식별자가 아닙니다(이슈 #33에 기록).
7. 12:23 이전에 만든 PC의 예전 체크아웃을 새 히스토리로 맞추거나 보관(백업 후 `fetch` + `reset --hard origin/main`). 그 전에는 거기서 푸시 금지.
8. 원격 브랜치 정리는 **2026-11-12 2차 통과까지 완료**했습니다. 1차에서 `main`에 완전히 포함된 32개를 삭제했고, 2차(04:05–04:15 KST, 전체 ref 번들 백업·검증 후)에는 **19개를 더 삭제**했습니다 — tip이 `main`의 조상인 8개와, `git cherry` 기준 패치 고유 커밋이 없어(모두 `-`) 내용상 이미 `main`에 있는 11개입니다. 남은 헤드는 **35개**이고, 그중 34개는 고유 커밋이 남아 있어 소유자를 위해 유지합니다. 목록: [`docs/ops/BRANCH-CLEANUP-2026-11-12.md`](ops/BRANCH-CLEANUP-2026-11-12.md).
