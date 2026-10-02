# 온톨로지·PowerCAD·JEV 교차 검증 및 동시 작업 인계
검증자: 이 ChatGPT 세션 / workspace e92060ed0692  
기준일: 2026-10-02 KST · 최종 메타데이터 관측 2026-10-02T11:07:24.259Z  
작업 범위: 읽기 전용 검증, 고정 커밋 복사본 검사, 새 문서 브랜치에만 보고서 추가.

## Claude와 다른 ChatGPT 세션이 먼저 읽을 사항
- 이 문서는 작업 잠금이나 작업자 간 실시간 동기화가 아니다. 다른 세션의 로컬 미커밋 변경은 볼 수 없고, GitHub에 올라온 상태만 확인했다.
- 기존 코드, 기본 브랜치, Claude/기존 ChatGPT 브랜치, 열린 PR, 배포, DB, Drive 원본에 변경을 수행하지 않았다. 병합·rebase·force-push·CI 재실행도 수행하지 않았다.
- 이 세션의 유일한 원격 변경 허용 범위는 `docs/chatgpt-audit-20261002-1105-e92060` 브랜치의 이 문서이다. 해당 브랜치를 다른 작업의 베이스로 사용하지 말고, 검증 근거로만 읽는다.
- 수정 담당자를 정한 뒤 작업한다. 동일 저장소·파일을 다른 에이전트가 수정 중이면 해당 에이전트의 완료/인계까지 변경하지 않는다. 기존 세션의 승인을 이 문서가 대신하지 않는다.
- 각 수정 전 최신 기본 HEAD/작업 HEAD/PR changed-files를 다시 조회한다. 이 보고서의 HEAD와 다르면 필요한 검증을 새 HEAD에서 반복한다.
- 각 작업자는 별도 clone/worktree와 고유 브랜치를 사용한다. 공유 checkout에서 checkout/reset/stash/clean을 하지 않는다. 공유 DB migration, ingestion/reembedding, CAD 실행, 전역 인덱스 재생성은 하나의 담당자에게만 맡긴다.
- 새 변경은 필요한 최소 파일로 분리하고 증거와 기준 SHA를 PR 본문에 기록한다. 이 감사는 수정·병합을 승인한 문서가 아니다.

## 관측 중 실제 변경
`Ontology/master`는 처음 읽은 `f3c6effb3d7b55ec2250b348a84c2ab5474e0c9e`에서
`2ab2346598a3987bccda954db8cfc18ba6b9f5c4`로 이동했다. 추가된 변경은 LightRAG 비교 어댑터와 관련 문서/테스트/CI 7개 파일이다.
최신 master CI가 성공한 것을 확인했다. 이 세션이 병합한 것이 아니다.
Claude PR #15는 여전히 open이며 head는 최초 `af28507416a1ca61e5109daa4320218551775b9d`에서 마지막 관측 `142f48f94ef84102944ffbee3327c1b88db253e8`로 이동했다.
기존 PR 파일 분석은 최초 head 기준이므로 마지막 head 전체의 검증 결과로 사용하지 않는다.
`power-cad-mcp`, `Ontology-platform`, `ArchOntos`, `jev-browser-control-plane` 기본 HEAD는 재조회에서 동일했다.

## 확인 범위와 증거 등급
- 인증된 저장소 검색에서 106개 반환 항목을 확인했고, 이름·기존 프로젝트 맥락으로 관련 후보 24개를 선정했다. 이는 연결 계정에서 발견된 범위이며, 모든 외부/로컬 프로젝트가 존재하지 않음을 뜻하지 않는다.
- 24개: 브랜치·열린 PR·최근 Actions 5개까지 조회. HS-CAD는 브랜치 2페이지, 총 159개까지 확인. CI 표의 '미확인'은 실패와 다르다.
- 핵심 5개: 커밋을 고정해 트리를 읽고 선택한 텍스트 321개를 별도 복사본으로 확보. Python 208개 AST, JSON 18개, TOML 5개 파싱 성공, 오류 0. 바이너리·실행파일·모든 산출물의 무결성 검증은 아니다.
- 로컬 실행: 실제 Ontology 코드의 JEV 외부 전송 기본 차단, context 경로 이탈 차단, JEV CLI 누락의 명시적 응답 3개 PASS. 외부 CLI/공급자 호출 없이 검사.
- 이 환경에 pytest, .NET SDK, PostgreSQL/AGE 실행환경 등이 없으므로 전체 pytest/dotnet/실 CAD 테스트를 새로 실행하지 않았다. CI 성공은 원격 실행 관측으로 표시했다.
- 실제 Drive 전체 적재량, 서버 배포 상태, CAD 2027에서 로딩·작도·단면·재저장, 대형 도면 성능은 미검증. 단위/시뮬레이션 CI를 실제 CAD 검증과 동일시하지 않는다.
- 과거 실패의 상세 로그는 ArchOntos와 JEV에서 404로 조회 불가였다. 실패 원인을 코드/결제/권한 문제 중 하나로 단정하지 않았다.

## 관련 저장소 목록
| 저장소 | 공개 상태 | 기본 브랜치 | 관측 HEAD | 열린 PR | CI 근거 |
|---|---|---|---|---|---|
| [Ontology](https://github.com/khs0927/Ontology) | public | master | `2ab2346598a3987bccda954db8cfc18ba6b9f5c4` | [#15](https://github.com/khs0927/Ontology/pull/15) | success · [최신 master 실행](https://github.com/khs0927/Ontology/actions/runs/36998466682) |
| [Ontology-platform](https://github.com/khs0927/Ontology-platform) | private | main | `7ec50e0a96449d395a953df967e43186cb5db1f5` | [#10](https://github.com/khs0927/Ontology-platform/pull/10), [#9](https://github.com/khs0927/Ontology-platform/pull/9) | success · [실행](https://github.com/khs0927/Ontology-platform/actions/runs/36952639818) |
| [ArchOntos](https://github.com/khs0927/ArchOntos) | private | main | `ac625a654611c52761cb5c1d2cf65dca3a8e5d09` | [#3](https://github.com/khs0927/ArchOntos/pull/3), [#2](https://github.com/khs0927/ArchOntos/pull/2), [#1](https://github.com/khs0927/ArchOntos/pull/1) | 기본 HEAD 일치 결과 미확인; 최근 failure (agent/mvp0-evidence-normalization) · [실행](https://github.com/khs0927/ArchOntos/actions/runs/36448124462) |
| [power-cad-mcp](https://github.com/khs0927/power-cad-mcp) | public | main | `ce392f9c39609d4a4c46b30791b0661a4d887495` | [#13](https://github.com/khs0927/power-cad-mcp/pull/13), [#2](https://github.com/khs0927/power-cad-mcp/pull/2) | success · [실행](https://github.com/khs0927/power-cad-mcp/actions/runs/36954152885) |
| [CAD-MCP](https://github.com/khs0927/CAD-MCP) | public | main | `bc552d643a9d67b7eabacde7369435d076a0d71e` | 없음 | 조회한 Actions 실행 없음 |
| [HS-CAD](https://github.com/khs0927/HS-CAD) | private | main | `미확인` | [#156](https://github.com/khs0927/HS-CAD/pull/156), [#155](https://github.com/khs0927/HS-CAD/pull/155), [#154](https://github.com/khs0927/HS-CAD/pull/154), [#147](https://github.com/khs0927/HS-CAD/pull/147), [#146](https://github.com/khs0927/HS-CAD/pull/146), [#127](https://github.com/khs0927/HS-CAD/pull/127), [#126](https://github.com/khs0927/HS-CAD/pull/126), [#124](https://github.com/khs0927/HS-CAD/pull/124), [#113](https://github.com/khs0927/HS-CAD/pull/113), [#107](https://github.com/khs0927/HS-CAD/pull/107), [#76](https://github.com/khs0927/HS-CAD/pull/76), [#74](https://github.com/khs0927/HS-CAD/pull/74), [#71](https://github.com/khs0927/HS-CAD/pull/71), [#70](https://github.com/khs0927/HS-CAD/pull/70), [#69](https://github.com/khs0927/HS-CAD/pull/69), [#68](https://github.com/khs0927/HS-CAD/pull/68), [#67](https://github.com/khs0927/HS-CAD/pull/67), [#66](https://github.com/khs0927/HS-CAD/pull/66), [#58](https://github.com/khs0927/HS-CAD/pull/58), [#57](https://github.com/khs0927/HS-CAD/pull/57), [#55](https://github.com/khs0927/HS-CAD/pull/55), [#54](https://github.com/khs0927/HS-CAD/pull/54), [#53](https://github.com/khs0927/HS-CAD/pull/53), [#52](https://github.com/khs0927/HS-CAD/pull/52), [#51](https://github.com/khs0927/HS-CAD/pull/51), [#50](https://github.com/khs0927/HS-CAD/pull/50), [#49](https://github.com/khs0927/HS-CAD/pull/49), [#48](https://github.com/khs0927/HS-CAD/pull/48), [#47](https://github.com/khs0927/HS-CAD/pull/47), [#46](https://github.com/khs0927/HS-CAD/pull/46), [#45](https://github.com/khs0927/HS-CAD/pull/45), [#44](https://github.com/khs0927/HS-CAD/pull/44), [#43](https://github.com/khs0927/HS-CAD/pull/43), [#42](https://github.com/khs0927/HS-CAD/pull/42), [#41](https://github.com/khs0927/HS-CAD/pull/41), [#38](https://github.com/khs0927/HS-CAD/pull/38), [#37](https://github.com/khs0927/HS-CAD/pull/37), [#35](https://github.com/khs0927/HS-CAD/pull/35), [#34](https://github.com/khs0927/HS-CAD/pull/34), [#33](https://github.com/khs0927/HS-CAD/pull/33), [#32](https://github.com/khs0927/HS-CAD/pull/32), [#31](https://github.com/khs0927/HS-CAD/pull/31), [#30](https://github.com/khs0927/HS-CAD/pull/30), [#29](https://github.com/khs0927/HS-CAD/pull/29), [#28](https://github.com/khs0927/HS-CAD/pull/28), [#27](https://github.com/khs0927/HS-CAD/pull/27), [#26](https://github.com/khs0927/HS-CAD/pull/26), [#25](https://github.com/khs0927/HS-CAD/pull/25), [#24](https://github.com/khs0927/HS-CAD/pull/24), [#23](https://github.com/khs0927/HS-CAD/pull/23), [#22](https://github.com/khs0927/HS-CAD/pull/22), [#21](https://github.com/khs0927/HS-CAD/pull/21), [#20](https://github.com/khs0927/HS-CAD/pull/20), [#19](https://github.com/khs0927/HS-CAD/pull/19), [#18](https://github.com/khs0927/HS-CAD/pull/18), [#17](https://github.com/khs0927/HS-CAD/pull/17), [#15](https://github.com/khs0927/HS-CAD/pull/15), [#14](https://github.com/khs0927/HS-CAD/pull/14), [#12](https://github.com/khs0927/HS-CAD/pull/12), [#10](https://github.com/khs0927/HS-CAD/pull/10), [#8](https://github.com/khs0927/HS-CAD/pull/8), [#7](https://github.com/khs0927/HS-CAD/pull/7), [#6](https://github.com/khs0927/HS-CAD/pull/6), [#5](https://github.com/khs0927/HS-CAD/pull/5), [#4](https://github.com/khs0927/HS-CAD/pull/4), [#1](https://github.com/khs0927/HS-CAD/pull/1) | 기본 HEAD 일치 결과 미확인; 최근 failure (feature/mobile-only-chatgpt-cad-app) · [실행](https://github.com/khs0927/HS-CAD/actions/runs/29245292674) |
| [GOD-CAD](https://github.com/khs0927/GOD-CAD) | private | main | `53188d828e37cea8653b990947a47e51c8577b6e` | 없음 | success · [실행](https://github.com/khs0927/GOD-CAD/actions/runs/34469160422) |
| [All-In-Cad](https://github.com/khs0927/All-In-Cad) | private | main | `421131c2b015723aa5ebd006f84c9eb5665b103d` | [#15](https://github.com/khs0927/All-In-Cad/pull/15) | failure · [실행](https://github.com/khs0927/All-In-Cad/actions/runs/36399200244) |
| [hs-steel-cad](https://github.com/khs0927/hs-steel-cad) | private | main | `a44a660168eb673de86be39d58cc955a10074b24` | 없음 | 조회한 Actions 실행 없음 |
| [mac-cad-bridge](https://github.com/khs0927/mac-cad-bridge) | private | main | `7905051dc3b75d5e575a9b5acbf87057596dfee2` | [#1](https://github.com/khs0927/mac-cad-bridge/pull/1) | 조회한 Actions 실행 없음 |
| [jev-browser-control-plane](https://github.com/khs0927/jev-browser-control-plane) | private | main | `5023ee0d5ef097cd66b0bad1893876dc39c11e10` | [#3](https://github.com/khs0927/jev-browser-control-plane/pull/3) | failure · [실행](https://github.com/khs0927/jev-browser-control-plane/actions/runs/36213114744) |
| [antigravity-jev-systemone](https://github.com/khs0927/antigravity-jev-systemone) | private | main | `232f5c540234c5543dacd2606a92bbbaa2052066` | 없음 | 조회한 Actions 실행 없음 |
| [korean-law-gpt-actions](https://github.com/khs0927/korean-law-gpt-actions) | private | main | `141a30be66b77a068ba39abe36c32fa9318e78e2` | [#26](https://github.com/khs0927/korean-law-gpt-actions/pull/26), [#25](https://github.com/khs0927/korean-law-gpt-actions/pull/25), [#23](https://github.com/khs0927/korean-law-gpt-actions/pull/23), [#22](https://github.com/khs0927/korean-law-gpt-actions/pull/22), [#18](https://github.com/khs0927/korean-law-gpt-actions/pull/18) | 기본 HEAD 일치 결과 미확인; 최근 failure (fix/pnu-land-auth-diagnostics) · [실행](https://github.com/khs0927/korean-law-gpt-actions/actions/runs/29710215053) |
| [korean-law-public-data-gpt-actions](https://github.com/khs0927/korean-law-public-data-gpt-actions) | private | main | `bccdfb04d24cbdcce180c45255c2dc091edcc265` | [#1](https://github.com/khs0927/korean-law-public-data-gpt-actions/pull/1) | 조회한 Actions 실행 없음 |
| [All-in-memory](https://github.com/khs0927/All-in-memory) | private | main | `c278d562cdcdfb9e6a98108b9b21e13b806e5b28` | 없음 | failure · [실행](https://github.com/khs0927/All-in-memory/actions/runs/35887640854) |
| [Edu-Foundry-Korea](https://github.com/khs0927/Edu-Foundry-Korea) | private | main | `81ac171ac1ba2633b67a61dec56b533df482d9c5` | [#8](https://github.com/khs0927/Edu-Foundry-Korea/pull/8), [#7](https://github.com/khs0927/Edu-Foundry-Korea/pull/7), [#6](https://github.com/khs0927/Edu-Foundry-Korea/pull/6), [#5](https://github.com/khs0927/Edu-Foundry-Korea/pull/5), [#4](https://github.com/khs0927/Edu-Foundry-Korea/pull/4), [#3](https://github.com/khs0927/Edu-Foundry-Korea/pull/3), [#2](https://github.com/khs0927/Edu-Foundry-Korea/pull/2), [#1](https://github.com/khs0927/Edu-Foundry-Korea/pull/1) | 기본 HEAD 일치 결과 미확인; 최근 failure (agent/security-posture-v0) · [실행](https://github.com/khs0927/Edu-Foundry-Korea/actions/runs/36596818616) |
| [-sketcharch-open](https://github.com/khs0927/-sketcharch-open) | private | main | `35c1084dd0328dd1a2cd5d570019294ec61f8618` | [#16](https://github.com/khs0927/-sketcharch-open/pull/16), [#15](https://github.com/khs0927/-sketcharch-open/pull/15), [#13](https://github.com/khs0927/-sketcharch-open/pull/13), [#12](https://github.com/khs0927/-sketcharch-open/pull/12), [#11](https://github.com/khs0927/-sketcharch-open/pull/11) | 기본 HEAD 일치 결과 미확인; 최근 failure (agent/local-mcp-control-clients) · [실행](https://github.com/khs0927/-sketcharch-open/actions/runs/29220151287) |
| [rhino-full-mcp](https://github.com/khs0927/rhino-full-mcp) | private | main | `3dcd9fe440abffe1084a3e30b47b91a27a07a882` | 없음 | 기본 HEAD 일치 결과 미확인; 최근 failure (agent/rhino-full-mcp-bridge) · [실행](https://github.com/khs0927/rhino-full-mcp/actions/runs/29797664386) |
| [rhino-mcp-opencode-version](https://github.com/khs0927/rhino-mcp-opencode-version) | private | main | `3ccc73a02cf1bc0b2c2b276ee574fd5899a8fb6c` | 없음 | failure · [실행](https://github.com/khs0927/rhino-mcp-opencode-version/actions/runs/29020324770) |
| [rhino-gpt-control-framework](https://github.com/khs0927/rhino-gpt-control-framework) | private | master | `e4370c6906265ee066e717ecad42ad208c05819b` | [#85](https://github.com/khs0927/rhino-gpt-control-framework/pull/85), [#82](https://github.com/khs0927/rhino-gpt-control-framework/pull/82), [#80](https://github.com/khs0927/rhino-gpt-control-framework/pull/80), [#78](https://github.com/khs0927/rhino-gpt-control-framework/pull/78), [#76](https://github.com/khs0927/rhino-gpt-control-framework/pull/76), [#54](https://github.com/khs0927/rhino-gpt-control-framework/pull/54), [#23](https://github.com/khs0927/rhino-gpt-control-framework/pull/23), [#21](https://github.com/khs0927/rhino-gpt-control-framework/pull/21), [#20](https://github.com/khs0927/rhino-gpt-control-framework/pull/20), [#18](https://github.com/khs0927/rhino-gpt-control-framework/pull/18), [#17](https://github.com/khs0927/rhino-gpt-control-framework/pull/17) | 기본 HEAD 일치 결과 미확인; 최근 failure (agent2/architectural-geometry-quality) · [실행](https://github.com/khs0927/rhino-gpt-control-framework/actions/runs/29648010747) |
| [freecad-mcp-1](https://github.com/khs0927/freecad-mcp-1) | private | main | `0f18ea44e8fbee4cdb61a68d3061d349ec5d13ff` | 없음 | 조회한 Actions 실행 없음 |
| [freecad-arch-mcp](https://github.com/khs0927/freecad-arch-mcp) | private | main | `9f10927542671cc70a1e330ddf44b4c95c413634` | [#1](https://github.com/khs0927/freecad-arch-mcp/pull/1) | 조회한 Actions 실행 없음 |
| [freecad-spkane-mcp](https://github.com/khs0927/freecad-spkane-mcp) | private | main | `bd0769a6989db4525aac012118ba4570a126a5e6` | [#1](https://github.com/khs0927/freecad-spkane-mcp/pull/1) | 기본 HEAD 일치 결과 미확인; 최근 failure (codex/upstream-import) · [실행](https://github.com/khs0927/freecad-spkane-mcp/actions/runs/30447204575) |
| [xicad](https://github.com/khs0927/xicad) | private | main | `c8ce84bc776ec21c7fba00e5b62000a48d0aaaed` | [#1](https://github.com/khs0927/xicad/pull/1) | 기본 HEAD 일치 결과 미확인; 최근 failure (agent/xicad-mcp-framework) · [실행](https://github.com/khs0927/xicad/actions/runs/29353797132) |

공개 상태는 조회 도구가 반환한 값이다. 공개/비공개 설정을 변경하지 않았다. 폭넓은 관련 후보는 메타데이터 검증 수준이며, 전체 코드 감사 완료를 의미하지 않는다.

## 핵심 프로젝트 관계
| 프로젝트 | 읽은 코드로 확인한 역할 | 경계 |
|---|---|---|
| Ontology | AEC CAIR 원본 연결, 도면 파싱, PostgreSQL/AGE/pgvector/PostGIS 검색, 교체 가능한 context/intelligence 확장 | 원본·CAIR와 파생 검색/그래프를 구분 |
| Ontology-platform | Sion entity/relation/evidence API, temporal relation, read/write scope, 선택적 CAIR 연합 조회, LightRAG projection | AEC 연합 결과는 canonical=false/read_only=true |
| ArchOntos | Evidence/Assertion/Rule/Decision 및 법규 MVP-0 골격 | 법규 판정 근거·버전과 검색 결과를 분리 |
| power-cad-mcp | C# AutoCAD 플러그인·.NET MCP 서버, Python DXF/COM 경로, Ontology 조회·후보 선택 | 컨텍스트 선택과 실제 CAD 변경은 별도 |
| jev-browser-control-plane | 공식 typesafe_sdk의 system_one 기반 Choice/Noul/Score wrapper | 현재 연결된 JEV Decision MCP Gateway와 저장소 main은 동일 배포라는 증거 없음 |

PowerCAD 현재 기본 HEAD의 native 플러그인은 `net10.0-windows`, `AutoCAD.NET 26.0.0`로 설정된 C# 코드이다.
검사한 전체 트리에는 C++ 소스 프로젝트가 없었다. 이는 저장소 구현 관측이며 Autodesk 제품 사양을 별도로 검증한 결론은 아니다.
CI에서는 Linux/Windows .NET build/test와 Windows bundle/self-contained server 패키지까지 성공했다.

## 확인된 장치
1. PowerCAD C# 컨텍스트: 현재 document_id 확인, numbered candidate/action, 10분 TTL, 재선택 시 fingerprint 재검증, `may_execute_mutation=false`.
2. Sion CAIR 클라이언트: remote URL에서 bearer 설정 필요, `canonical=false`/`read_only=true` 응답을 요구.
3. Ontology intelligence bridge: 저장소 내부 경로만 허용, JEV 소스 전송 기본 금지, 실행 prefix 제한, 파생 출력 경계.
4. 최신 Ontology LightRAG 어댑터: 기본 disabled, remote HTTPS/API key/image digest 요구, chunk_id의 로컬 provenance binding 확인. 파일명이나 응답 내용으로 근거를 임의 생성하지 않는 구조.
5. Ontology-platform main CI 로그에서 **27 passed, 1 warning** 확인. 경고는 FastAPI/Starlette test client의 httpx 사용 관련이다.
6. PowerCAD main CI의 lint, Python 6개 OS/버전 조합, .NET 2개 OS, package-windows, wheel build가 모두 success였다.

## 후속 점검·수정 후보
### F01 — Ontology 운영 API 인증 및 노출 경계 (우선)
**확인된 코드:** `src/aec_intelligence/operational/api.py`의 ingestion/retry/review 등 변경 endpoint에 인증 dependency가 없고 CORS는 wildcard+credentials 설정이다. `docker-compose.yml`은 `58000:8000`으로 loopback IP 없이 포트를 publish한다.
최신 master에서 해당 api.py blob이 이전과 동일함을 재확인했다.
**영향:** 이 구성을 네트워크에 노출하면 연결 가능한 호출자의 조회/변경을 API 코드가 인증으로 제한하지 않는다. 실제 방화벽/프록시/배포 노출 상태는 확인하지 않았다.
**담당 작업:** 배포 담당자와 범위를 정해 loopback 바인딩 또는 인증된 게이트웨이 및 API read/write 권한을 적용. 인증 없는 변경 요청 거부와 read-only 클라이언트 권한 테스트.
**충돌 주의:** Claude PR #15의 운영 파이프라인과 같은 저장소다. 인증/compose/API를 맡을 작업자를 지정하기 전 이 감사 세션에서 수정하지 않았다.

### F02 — PostgreSQL 오류 후 fallback의 transaction 복구 누락 (우선)
**확인된 코드:** `operational/db.py:Database.connect`는 autocommit을 설정하지 않고 AGE LOAD를 먼저 실행한다.
`operational/search.py:SearchRouter.search`는 vector SQL 오류를 잡은 뒤 같은 connection에서 fallback SQL을 실행한다. `_get_relations`도 Cypher 실패 뒤 같은 connection에서 SQL fallback을 실행한다.
catch 경로에 rollback/savepoint가 없다.
**판단:** PostgreSQL 서버 SQL 오류는 transaction을 실패 상태로 만들 수 있으므로 이후 fallback도 실패할 가능성이 높다. AGE 자체가 없으면 connect의 LOAD에서 먼저 실패해 'AGE 없는 DB fallback' 설명과도 맞지 않는다.
**미검증:** 장애를 넣은 실제 PostgreSQL 재현은 수행하지 않았다. 최신 master search.py는 blob 동일.
**담당 작업:** 오류 격리를 savepoint 또는 별도 읽기 connection으로 구현하고, vector SQL 오류/AGE query 오류 뒤 lexical/SQL relation fallback이 실제 성공하는 회귀 테스트. 데이터 일부 오류를 광범위하게 숨기지 않도록 warning도 확인.

### F03 — PowerCAD 후보 handle의 원본 도면 연결 검증 (우선 회귀 검증)
**확인된 코드:** `dotnet/PowerCad.Server/OntologyContext.cs:Query`는 hit.geometry_ref 마지막 hex token을 handle로 추출하고 현재 도면에서 조회해 fingerprint를 저장한다.
문서 ID 보호는 현재 활성 도면이 바뀌는 것을 막지만, 각 hit의 원본 도면과 현재 도면의 동일성을 대조하는 검사는 이 메서드에서 확인되지 않는다.
**위험 시나리오:** 과거/다른 도면의 hit와 현재 도면 객체가 같은 handle을 쓰면 현재 객체를 잘못 semantic candidate로 붙일 수 있다. 현재 객체의 fingerprint가 정상이어도 원본 대응까지 증명하지 않는다.
**미검증:** 두 실제 DWG를 이용한 재현은 하지 않았고, 다른 호출 경로가 원본을 제한하는지도 추가 확인 필요하다.
**담당 작업:** 서로 다른 source/document/revision에서 같은 handle인 fixture로 검증. source/document identity와 revision/hash를 대조하고 불일치 후보는 제외. JEV choice는 이 검증을 대체하지 않는다.
**충돌 주의:** Python ontology.py는 Claude PR #13 변경 파일이므로 동시에 수정하지 않는다.

### F04 — C# Ontology stdio 프로세스 수명·stderr 처리
`OntologyMcpClient.CallAsync`는 stderr를 redirect하지만 stdout 완료/프로세스 exit 이후에 읽는다. 자식이 stderr를 많이 쓰면 buffer가 차서 timeout까지 정지할 수 있다.
또 initialize 응답을 확인하기 전에 initialized/tools-call을 보낸다.
**담당 작업:** stderr를 동시에 drain하고 init 응답/프로토콜 협상·호출 오류를 확인; 외부 cancellation에서 자식 프로세스가 남지 않는지 검사.
**등급:** 정적 코드 검토 후보; 실제 hang/cancellation 재현 미수행. 제공된 aec-mcp와의 성공 CI가 모든 외부 서버의 호환성을 증명하지 않는다.

### F05 — JEV main wrapper와 실제 Gateway validation 차이
`jev-browser-control-plane/main:router.py:noul`은 non-empty criteria를 SDK로 전달하고 true/false 키 집합은 직접 검사하지 않는다.
반면 **현재 연결된 Gateway**의 negative test는 priority 키를 **VALIDATION_ERROR**로 거부하고 `upstream_called=false`, `retry_automatically=false`를 반환했다.
따라서 '현재 Gateway에서 오류가 아직 재현된다'고 보고하지 않는다. 저장소 wrapper를 직접 사용하는 경로에 validation을 일관되게 적용할 필요가 있다.
`jev-browser-control-plane`의 PR #3은 OpenCode Zen Free 경로이며 공식 TypeSafe 연결의 정상/무료 근거로 사용하지 않는다. 해당 PR도 변경하지 않았다.

### F06 — 오래된 열린 PR와 단계형 PR 정리
Ontology-platform #9/#10, ArchOntos #1/#2/#3, PowerCAD #2 및 관련 CAD 저장소에는 열린 기존 PR들이 있다.
기본 브랜치가 발전했으므로 PR 제목/과거 CI만으로 현재 필요한 변경인지 판단하면 중복 또는 회귀를 만들 수 있다.
**담당 작업:** 담당자가 최신 base/head diff와 이미 반영된 변경을 확인하고 필요한 부분만 새 최소 PR로 분리. 이 감사에서 close/merge/rebase하지 않았다.

## 동시 작업 파일 지도
| 작업 | 관측 브랜치/PR | 피해야 할 동시 수정 |
|---|---|---|
| Claude AEC 파싱/실행 | Ontology `claude/project-thread-55x5g9`, PR #15 | dwg.py, classifier.py, dxf.py, ontology.py, mcp_gateway.py, pipeline.py, rebuild.py, validation_engine.py, operational config/cli/embeddings/parsers/worker, spatial/PDF 신규 파일, ops 스크립트 및 관련 tests |
| 기존 ChatGPT LightRAG 비교 | Ontology `feat/lightrag-comparison-20261002`; 검증 도중 master에 동일 범위 추가 관측 | intelligence-safety.yml, drawing_context policy/README/VALIDATION, lightrag_http.py와 tests |
| Claude PowerCAD 검색 | power-cad-mcp `claude/project-thread-pyz4nr`, PR #13 | README.md, src/power_cad_mcp/ontology.py, tests/test_ontology.py, tests/test_ontology_live.py |
| JEV 기존 Claude 작업 | jev-browser-control-plane `claude/gallant-lovelace-6vkbzz`, PR #3 | 별도 무료 경로 실험; 공식 Gateway와 구분하고 작업자에게 최신 상태 확인 |
| 이 감사 세션 | Ontology-platform `docs/chatgpt-audit-20261002-1105-e92060` | 이 보고서만 새로 추가; 소스·기존 문서는 미수정 |

최초 비교에서 Ontology Claude PR #15의 33개 changed-files와 LightRAG 7개 changed-files는 직접 경로 교집합이 없었다.
그러나 런타임·의존성·동일 DB는 공유할 수 있고 이후 Claude head도 이동했으므로 '충돌 없음 보장'으로 읽지 않는다.
작업자 식별은 PR body의 Claude 표시/브랜치명과 기존 대화 맥락에 근거한 관측이며, commit author만으로 모든 수정 주체를 확정하지 않았다.

## JEV 실제 호출 기록
- 정상 Noul: 동시 작업 브랜치를 유지하고 별도 문서 브랜치를 사용할지 판단하는 요청 → `status=ok`, `noul=0.94`, `model=jev-1.13.0`, `advisory_only=true`, `threshold_status=uncalibrated`.
- 잘못된 criteria(priority) → `status=validation_error`, `code=VALIDATION_ERROR`, `upstream_called=false`, 자동 재시도 금지.
- 입력에는 이 작업의 요약과 공개 관측 사실만 넣었고 코드·토큰·DB/Drive 데이터는 보내지 않았다.
- JEV 결과는 승인·테스트·정확성의 대체물이 아니다. 이번에 Choice/Score/batch를 호출한 것은 아니다.
- 이 Gateway의 source SHA/실제 배포 환경을 이 저장소 main과 대조하지 않았으므로 양자가 동일하다고 단정하지 않는다.

## Claude/ChatGPT 인계 지시문
> 이 감사 보고서를 먼저 읽고 현재 GitHub 기본 HEAD와 작업 HEAD를 다시 확인하세요. 기존 다른 에이전트 브랜치와 미커밋 변경을 보존하세요. F01/F02/F03은 각각 배포 접근 보호, DB 오류 후 fallback, CAD 원본 도면 대응 검증으로 범위가 다릅니다. 담당 파일을 하나씩 선언하고 별도 worktree/브랜치에서 처리하세요. PR #15와 #13의 최신 changed-files를 확인해 겹치는 파일은 기존 담당자에게 맡기세요. 감사 문서 브랜치를 merge하지 말고 근거로 읽으세요. 수정 결과에는 기준 SHA, 실제 테스트 범위, skip 사유, live 미검증 항목을 기록하세요. 원본 Drive/CAIR, 공유 DB, CAD 변경은 이미 진행 중인 담당 실행과 동시에 수행하지 마세요.

## 재현 및 재검증
- 로컬 정적 검사: Python `ast.parse` (UTF-8 BOM 제거), JSON `json.loads`, TOML `tomllib.loads`.
- 전체 검사 재실행 명령은 각 저장소의 해당 SHA CI workflow를 따를 것. pytest/SDK 설치와 DB 구동은 별도 환경에서 수행.
- Ontology: 고정 SHA의 `.github/workflows/intelligence-safety.yml`; PostgreSQL/AGE/pgvector/PostGIS job 포함.
- Ontology-platform: 고정 SHA의 `.github/workflows/tests.yml`; 관측 CI는 test+graphrag extras 설치 후 pytest 27개 통과.
- PowerCAD: 고정 SHA의 `.github/workflows/ci.yml`; Python/DXF와 .NET simulated tests + Windows packaging. 실제 AutoCAD smoke는 설치된 사용자 환경에서 별도로 수행.
- ArchOntos/JEV의 실패는 해당 HEAD에서 재현 후 코드 실패/실행 전 인프라 실패를 구분할 것.
- 최종 문서 게시 직전 기본 HEAD를 재조회하고 이동 여부를 인계한다. 게시 후 다른 세션이 변경하면 이 보고서는 해당 시점의 스냅샷이다.
