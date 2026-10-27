---
name: sketchup-mcp
description: >-
  열려 있는 SketchUp 모델을 sketchup-mcp2 또는 hueflow-sketchup MCP 서버로 조회하거나
  모델링할 때 사용한다(모델 정보, 컴포넌트 검색, 태그, 재질, 프리미티브 생성, 변형, 뷰포트
  캡처, Ruby 실행). Use for SketchUp inspection or modelling through local MCP servers.
---
# SketchUp MCP 사용

SketchUp용 로컬 MCP 서버는 두 개를 씁니다. 둘 다 [`local-cad-mcp-bridge`](../local-cad-mcp-bridge/SKILL.md)로
호출하고, 도구 전체 목록은 [`docs/mcp/TOOL-CATALOG.ko.md`](../../docs/mcp/TOOL-CATALOG.ko.md)에 있습니다.
무엇을 어떻게 그릴지는 [`docs/sketchup/MODELING-GUIDELINES.ko.md`](../../docs/sketchup/MODELING-GUIDELINES.ko.md)와
[`docs/sketchup/GROUPING-WORKFLOW.ko.md`](../../docs/sketchup/GROUPING-WORKFLOW.ko.md)를 따릅니다.

## 서버 고르기

| | `sketchup-mcp2` (22) | `hueflow-sketchup` (21) |
|---|---|---|
| SketchUp 측 전제 | SketchUp 실행 + 확장 TCP 서버(9876, 추정) | **Plugins > MCP Server > Start Server** (포트 8080) |
| 단위 | 항상 mm, 각도 degree | 모델 단위(미터법이 아니면 inch) |
| 강점 | 검색·페이지네이션(`list_components`, `find_components`), 뷰포트 캡처, 조인트·불리언·모따기, `undo` | 면/모서리/원/호/다각형 생성, `push_pull`, `follow_me`, 태그·재질 목록, `create_roof_truss` |
| 임의 코드 | `eval_ruby` (확장 설정에서 사용자가 끌 수 있음) | `execute_ruby` (SU_MCP 모듈 컨텍스트) |
| 알려진 문제 | 2026-10-08 13:50 KST `initialize` 멈춤 사례 | 플러그인 서버를 SketchUp 재시작마다 다시 켜야 함 |

`sketchup`(cursor 항목)은 `sketchup_mcp` 모듈이 없어 쓰지 않습니다.

## 절차

1. 상태 확인: `sketchup-mcp2.get_version` → `get_model_info` (또는 `hueflow-sketchup.get_model_info`).
   파일 경로·단위·엔터티 수를 사용자에게 보여 주고 대상 모델이 맞는지 확인합니다.
2. 조회: `list_layers`, `find_components`(이름 부분일치·태그·종류), `get_component_info`, `get_selection`,
   `list_components`(`limit`/`offset`/`response_format`으로 나눠 받기). 큰 모델은 `max_depth`를 작게 시작합니다.
3. 시각 확인: `get_viewport_screenshot`(`view_preset`, `zoom_extents`, `restore_view`).
4. 변경(승인 후): 생성(`create_component`, `create_layer`, hueflow `create_box`/`create_face` 등) →
   배치·변형(`transform_component`는 bbox 최소점 기준 **절대 위치**, hueflow `move_entity`는 **상대 벡터**) →
   재질(`set_material`).
5. 검증: 변경 뒤 `get_component_info`/`get_viewport_screenshot`으로 결과를 확인하고 사용자에게 보고합니다.
6. 되돌리기: sketchup-mcp2는 도구 호출 하나가 Undo 한 단계(`undo`). Ruby는 `start_operation`으로 묶습니다.

## 확인이 필요한 도구

`delete_component`, `boolean_operation`(`delete_originals`), `transform_component`, `chamfer_edge`/`fillet_edge`
(기본값이 **모든 모서리**), `export_scene`, `eval_ruby`, `execute_ruby`, hueflow의 `move_entity`/`rotate_entity`/
`scale_entity`/`push_pull`/`follow_me`. 실행 전 대상 ID·변경 내용·되돌리기 방법을 설명하고 승인을 받습니다.

## Ruby 읽기 스크립트

모델 덤프 같은 읽기 작업은 [`scripts/sketchup/`](../../scripts/sketchup/README.md)의 읽기 전용 스크립트
(`dump_model.rb`, `geom_probe.rb`, `grouping_probe.rb`, `render_views.rb`)를 `eval_ruby`/`execute_ruby`로 실행합니다.
코드 전문을 보여 주고 읽기 전용임을 밝힌 뒤 실행하며, 결과 JSON은 `--out`으로 받습니다.

```ruby
model = Sketchup.active_model
model.start_operation('MCP edit', true)
begin
  # ... 변경 ...
  model.commit_operation
rescue => e
  model.abort_operation
  raise e
end
```

## 주의

- 두 서버의 단위를 섞지 않습니다(mm vs inch). hueflow 좌표는 `get_model_info`의 단위를 먼저 확인합니다.
- `list_entities`/`list_components` 전체 출력은 매우 클 수 있으니 필터와 페이지를 씁니다.
- 저장하지 않은 모델일 수 있으므로 대량 변경 전에 사용자에게 저장을 권합니다.

## Hueflow와 mcp2 동시구동 (2026-10-27)
정본: Drive 지침 `26_Hueflow_mcp2_동시구동_2026-10-27.md`.
- 포트: mcp2(MCPforSketchUp) `127.0.0.1:9876` TCP, Hueflow `127.0.0.1:8080` HTTP. **둘 다 Listen이 정상·권장**. QGIS 9877, Blender는 9876 금지.
- 역할: 작도·검색·undo·뷰포트 주경로는 `sketchup-mcp2`. Hueflow는 면/모서리/호/push_pull 보완·폴백. Hueflow가 먼저 응답해도 주 도구를 바꾸지 않음.
- 단위: mcp2 항상 mm, Hueflow는 모델 단위(inch 가능) → 쓰기 전 `get_model_info`. 한 세션에서 좌표 혼용 금지.
- 쓰기: 두 서버에서 동시에 `eval_ruby`/`execute_ruby`/형상 변경 금지(단일 UI 스레드). 읽기 병렬은 OK.
- 기동: mcp2는 `mcp_for_sketchup_autostart.rb`(로그 `%TEMP%\mcp2-autostart.log`), PrivatePreferences `mcp_for_sketchup.rb`=1 유지(0이면 메뉴/상수 미로드). Hueflow는 메뉴 Start.
- 장애: 8080이 accept만 하고 무응답이면 Ruby 타이머 hang → mcp2도 먹통 가능. 저장 후 SketchUp 재시작(강제종료 금지), Ruby Console require+start, HARD ERROR면 로딩 정책 Identified/Unrestricted.
- 클라이언트: 여러 에이전트가 각자 stdio로 sketchup-mcp2를 띄워도 OK. 충돌은 플러그인 포트와 동시 쓰기뿐.
- whl 0.4.0, `UV_CACHE_DIR=C:\Users\USER\.cache\uv-sketchup-mcp2`. 경로는 `C:\Users\USER` (khs09 아님).
- 검증: `Get-NetTCPConnection -LocalPort 9876,8080 -State Listen`, `sketchup-mcp2.get_version`(compatible true), `hueflow-sketchup.get_model_info`.
