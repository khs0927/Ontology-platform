# Sion Ontology Platform — 현재 상태 (한국어 요약)

갱신: 2026-10-08 저녁 (Asia/Seoul)

## 아키텍처 (요약)

1. **메인 모노레포** `khs0927/Ontology-platform` (v0.2.0). GitHub가 코드 이력의 기준이다.
2. **병합된 패키지**: `packages/regulation`(ArchOntos), `packages/aec`(Ontology/`aec_intelligence`), `packages/cad/god-cad`(GOD-CAD). 원본 저장소는 보관(읽기 전용).
3. **브릿지 전용(별도 저장소)**: power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad, CAD-MCP. 버전된 JSON 계약 + 계약 테스트로만 연결. Sion은 CAD를 직접 수정하지 않는다.
4. **런타임 DB**: 로컬 PostgreSQL(또는 SQLite 스모크). `public` + `regulation` 스키마. 라이브 DB는 디스크에 두고, 커밋된 쓰기마다 `SION_STORAGE_ROOT`(Drive 데스크톱 폴더)로 스냅샷·그래프를 export한다.
5. **수집**: 문서(PDF/DOCX/md…), DXF(`sion_cad.reader`), IFC, 에이전트 세션 브릿지(Antigravity/Codex/Claude + DeepSeek/Hermes/ZCode 로컬 로그 리더).
6. **관계·리뷰**: 31노드/43관계는 `unverified` 후보로 적재. `/review`에서 사람이 승인·반려. SketchUp 0914 지식팩(노드 1,195 / 관계 4,509)도 후보·검증 혼합.
7. **GraphRAG / 검색**: LightRAG 경계, 임베딩·벡터 검색, AEC/CAIR 읽기 전용 페더레이션. 쓰기는 `write:knowledge` 스코프.
8. **CI**: Tests(Ubuntu+Windows), Verify, AEC/CAD, Regulation, Public security. agent-bridge Windows exe는 Releases.

## 2026-10-08 저녁 스프린트 결과 (20:50 재확인)

**Ontology-platform 병합** (모두 CI 통과 후 병합)
- [#37](https://github.com/khs0927/Ontology-platform/pull/37) 보관된 Ontology #86/#90/#91 이식 — 읽기 전용 브리지 fail-closed 계약 + 근거 수명주기.
- [#38](https://github.com/khs0927/Ontology-platform/pull/38) 보관된 Ontology #80 이식 — RAM 부족·원본 폴더 없음에도 워커가 죽지 않고 대기·재시도, 속도/ETA 계산 수정.
- [#39](https://github.com/khs0927/Ontology-platform/pull/39) `switch-to-monorepo.ps1` + 한국어 런북 — 기본 드라이런, `-Apply`로 실행, DB 볼륨이 바뀌면 거부.
- [#40](https://github.com/khs0927/Ontology-platform/pull/40) netguard가 fake-IP 대역 `198.18.0.0/15`를 로컬로 오인하던 보안 문제 수정.
- [#41](https://github.com/khs0927/Ontology-platform/pull/41) 상태 문서 + 이 한국어 요약.
- #34·#35는 #36(Windows pytest)로 대체되어 닫음.

**연결 저장소 병합** (각 저장소에서 진행)
- power-cad-mcp #42(철골 플레이북), #40(문서 동기화), #43(`cad_hs_*` 자산 도구 10개, 전체 65개, `..` 경로 탈출 수정).
- hs-steel-cad #7 자산 레지스트리(819개, Windows 줄바꿈 해시 문제 수정).
- korean-land-mcp #1 CI 추가(테스트 29개). HS-CAD #157. All-In-Cad 테스트 96개 통과(병합 없음).

**후속 스프린트(sprint2/) 병합**
- [#42](https://github.com/khs0927/Ontology-platform/pull/42) 연결 저장소 계약을 10/8 저녁 최신 커밋으로 재고정, 계약 테스트 58 → 81개, `hs-steel-section-catalog/1` 스키마 추가.
- [#44](https://github.com/khs0927/Ontology-platform/pull/44) 일괄 판정 API `POST /api/v1/relations/candidates/bulk` + 한국어 `/review` 일괄 화면(필터·단축키·표시 전용 추천 힌트, 자동 승인 없음).
- [#45](https://github.com/khs0927/Ontology-platform/pull/45) 테스트 의존성 httpx2, `uv.lock` 알려진 취약점 0.
- korean-land-mcp #2 npm audit 20 → 2건. HS-CAD #158 Pillow ≥ 12.3, `opencode.json`은 커밋된 키 대신 `{env:GOOGLE_GENERATIVE_AI_API_KEY}` 사용.
- power-cad-mcp #44 `FakeTimeProvider`로 `OntologyAskTests` 결정적 테스트화(Windows 타이밍 간헐 실패 해결).

**20:50 기준 열림:** power-cad-mcp #45(HS-STEEL 스킬)·#46(CAD 없는 자산 수집 + Graph RAG 인덱스)·#47(headless DXF)·#48(`cad_hs_search`/`cad_hs_index_status`).
보관된 Ontology #88 headless 테스트 이식은 다시 하기 전에 열린 PR 확인. HS-CAD PR 분류 완료: 32개 닫음(이미 main에 포함), 병합 0, 34개 열림(한국어 코멘트). xiCAD `mcp==1.28.1` 고정은 Python 3.13에서 깨짐.

**새 문서**
- [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) — 메인 PC 복귀 시 순서대로 실행할 체크리스트(명령·성공 기준·롤백).
- [`docs/guidelines/AGENT-WORKFLOW.ko.md`](guidelines/AGENT-WORKFLOW.ko.md) — 이번 주 작업에서 정리한 에이전트 작업 지침.

## 소유자(오너) 할 일

0. **최우선(어느 PC든):** HS-CAD `opencode.json`에 커밋됐던 Google AI Studio API 키 교체(2026-05-21부터 공개 히스토리, main은 #158로 환경변수 사용) → HS-CAD 비밀 스캔 알림 #1을 "Revoked"로 닫기. 선택: power-cad-mcp·hs-steel-cad·All-In-Cad에 Dependabot + 비밀 스캔 켜기. 자세한 절차는 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 맨 위.
0b. HS-CAD PR 판단: 분석 체인 2개(#23/#25/#27/#29/#32/#34/#35, #24/#26/#28/#30/#31/#33/#37) main 포함 확인 후 닫기, #1/#4/#5/#7은 필요한 모듈만 새 PR로 이식, #12는 현재 `main.py` 기준 재작성, 실기 실행은 Windows + ZWCAD PC 필요. 자세한 내용은 to-do 문서의 HS-CAD 절.
1. `/review`에서 맵 후보 43건 + SketchUp 분류 214건·워크플로 링크 승인/반려 (이슈 #33).
2. 메인 PC 온라인 시 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 실행 — 보관된 Ontology 체크아웃 → `packages/aec` 전환(`switch-to-monorepo.ps1` 드라이런 후 `-Apply`).
3. `AutoSync_Code_To_GDrive` 예약작업 비활성화 확인 (라이브 DB 복사 금지).
4. 전환 후 GraphRAG 재색인(FAILED 커뮤니티 6건 재시도).
5. 운영 방화벽 스크립트 관리자 실행(18080/22217), DB 덤프를 DB와 다른 디스크로 복사.
6. SketchUp 덤프 경로(`skp_path`) 보존 여부 결정.
