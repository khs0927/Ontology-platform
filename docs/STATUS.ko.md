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

## 2026-10-08 저녁 스프린트 결과 (20:30 재확인)

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

**후속(막지 않음):** 보관된 Ontology #88 headless 테스트 이식, `/review` 일괄 처리, 계약 고정 커밋 갱신, 의존성 점검은
후속 스프린트에서 진행 — 다시 하기 전에 열린 PR 확인. power-cad-mcp Windows 타이밍 테스트 간헐 실패, HS-CAD 오래된 PR 약 28개 정리 필요.

**새 문서**
- [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) — 메인 PC 복귀 시 순서대로 실행할 체크리스트(명령·성공 기준·롤백).
- [`docs/guidelines/AGENT-WORKFLOW.ko.md`](guidelines/AGENT-WORKFLOW.ko.md) — 이번 주 작업에서 정리한 에이전트 작업 지침.

## 소유자(오너) 할 일

1. `/review`에서 맵 후보 43건 + SketchUp 분류 214건·워크플로 링크 승인/반려 (이슈 #33).
2. 메인 PC 온라인 시 [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) 실행 — 보관된 Ontology 체크아웃 → `packages/aec` 전환(`switch-to-monorepo.ps1` 드라이런 후 `-Apply`).
3. `AutoSync_Code_To_GDrive` 예약작업 비활성화 확인 (라이브 DB 복사 금지).
4. 전환 후 GraphRAG 재색인(FAILED 커뮤니티 6건 재시도).
5. 운영 방화벽 스크립트 관리자 실행(18080/22217), DB 덤프를 DB와 다른 디스크로 복사.
6. SketchUp 덤프 경로(`skp_path`) 보존 여부 결정.
