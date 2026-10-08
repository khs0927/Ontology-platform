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

## 소유자(오너) 할 일

1. `/review`에서 맵 후보 43건 + SketchUp 분류 214건·워크플로 링크 승인/반려 (이슈 #33).
2. 메인 PC(DESKTOP-KTQHS1I) 온라인 시 런타임을 보관된 `C:\CODE\Ontology` → 이 모노레포 `packages/aec`로 전환.
3. `AutoSync_Code_To_GDrive` 예약작업 비활성화 확인 (라이브 DB 복사 금지).
4. 전환 후 GraphRAG 재색인.
5. SketchUp 덤프 경로(`skp_path`) 보존 여부 결정.
