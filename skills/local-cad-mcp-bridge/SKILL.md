---
name: local-cad-mcp-bridge
description: >-
  Windows PC에 설정된 로컬 MCP 서버(SketchUp, Revit/Horizun, AutoCAD, power-cad,
  multiCAD, ZWCAD/xicad, FreeCAD, Rhino/Grasshopper, korean-law/land, kordoc, jev)를
  grokbot-mcp-bridge로 띄워 도구 목록을 보거나 도구를 호출할 때 사용한다. Use when the
  user wants to drive a Windows-local CAD/AEC MCP server on their own PC.
---
# 로컬 CAD MCP 브리지

Revit, SketchUp, AutoCAD, ZWCAD, Rhino 같은 데스크톱 앱과 통신하는 MCP 서버는 Windows에서만 동작하므로
Linux 박스나 원격 에이전트에서 직접 띄울 수 없습니다. 대신 사용자 PC의 브리지 스크립트가 설정된 stdio 서버를
띄우고, MCP 핸드셰이크를 한 뒤 도구를 나열하거나 호출하고 JSON을 출력한 다음 프로세스 트리를 정리합니다.

- 소스: [`tools/grokbot-mcp-bridge/`](../../tools/grokbot-mcp-bridge/README.md)
- 규칙과 서버별 문제 해결: [`docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md`](../../docs/mcp/LOCAL-CAD-MCP-OPERATIONS.ko.md)
- 도구 이름: [`docs/mcp/TOOL-CATALOG.ko.md`](../../docs/mcp/TOOL-CATALOG.ko.md)

## 위치

- PC의 브리지 폴더: `C:\Users\USER\grokbot-mcp-bridge\` (`mcp-call.mjs`, `README.md`, `overrides.json`, `test-results\`).
  저장소의 `tools/grokbot-mcp-bridge/`를 이 위치에 복사해 설치합니다.
- Grok Bot에서는 ListMachines로 PC를 찾고 그 `machineId`로 Shell을 실행합니다(호출마다 사용자 로컬 승인 필요).
- 서버 소스는 `~\.cursor\mcp.json`, `%APPDATA%\Claude\claude_desktop_config.json`, `~\.codex\config.toml`과
  수동 항목(`horizun-revit`)을 합칩니다. 이름만 쓰면 cursor → claude → codex → manual 순으로 해석하고,
  다른 소스는 `source:name`(예: `codex:power-cad`)으로 지정합니다.
- 서버별 cwd/timeout 보정은 `overrides.json`에만 넣고 사용자 설정 파일은 고치지 않습니다.

## 명령 (PowerShell)

```powershell
cd C:\Users\USER\grokbot-mcp-bridge
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs servers
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs tools <server> --brief [--out f.json] [--timeout 30000]
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs call <server> <tool> --args-file f.json [--timeout 120000]
```

도구 인자는 JSON 파일로 쓰고 `--args-file`로 넘깁니다(PowerShell 따옴표 문제 회피).
종료 코드 `1` = 브리지/기동 실패(`stage`, `stderrTail` 포함 JSON), `3` = 도구가 `isError` 반환.

## 절차

1. **앱과 플러그인 확인**: `Get-Process SketchUp,Revit,acad,ZWCAD,Rhino`. 포트 확인
   (`Get-NetTCPConnection -State Listen -LocalPort 8080,9876`): MCPforSketchUp 9876, Hueflow 8080.
   꺼져 있으면 사용자에게 모델을 열고 플러그인 서버를 시작해 달라고 요청합니다
   (Hueflow: **Plugins > MCP Server > Start Server**).
2. **읽기 전용 상태 도구 먼저**: `get_model_info`/`get_version`(SketchUp), `horizun_health`(Revit),
   `cad_status`/`cad_list_targets`(power-cad), `search_tools`(autocad-mcp).
3. **스키마 확인**: `tools <server> --out`으로 정확한 스키마를 본 뒤 호출합니다. 도구 이름을 추측하지 않습니다.
4. **확인 후 실행**: 삭제·덮어쓰기·저장·임의 코드 실행(`eval_ruby`, `execute_ruby`, 변경 도구를 부르는 `call_tool`)은
   무엇이 바뀌는지 설명하고 사용자 승인을 받은 뒤에만 실행합니다.
5. **비밀값**: 설정이나 환경 변수의 키를 출력하지 않습니다. `servers`는 자동으로 가리며 `--show-secrets`는 쓰지 않습니다.
6. 큰 결과는 `--out`으로 저장하고 요약만 보고합니다.

## 서버 메모 (2026-10-08 KST 기준)

- `xicad-headless`는 도구가 938개라 항상 `--brief` 또는 `--out`을 씁니다.
- npx/uvx 서버는 첫 기동에 30–150초가 걸릴 수 있으니 `--timeout`을 늘립니다.
- `autocad-mcp`는 `search_tools`, `call_tool` 두 개만 노출합니다(검색 모드): 먼저 검색하고 호출합니다. AutoCAD 2027 실행 필요(COM).
- `codex:power-cad`는 AutoCAD 재시작 후 `--target autocad-2027-<pid>`가 낡을 수 있으니 `cad_list_targets`로 확인합니다.
- `multiCAD-mcp`는 cwd `C:\CODE\multiCAD-mcp`가 필요합니다(`overrides.json`에 있음).
- `sketchup-mcp2`가 `initialize`에서 멈추면 `--verbose`로 stderr를 보고, 안 되면 `hueflow-sketchup`으로 대체합니다.
- `sketchup`(cursor, `sketchup_mcp` 모듈 없음)과 `revit-mcp`(`C:\CODE\revit-mcp` 없음)는 고장 상태입니다.
- `horizun-revit`(111개)은 Revit add-in이 배포되어야 실제 호출이 됩니다(Revit 2024/2027, `E:\Program files`).

## SketchUp: Hueflow + mcp2 coexistence (2026-10-27)
- Ports 9876 (mcp2, TCP) and 8080 (Hueflow, HTTP) **both Listening at once is normal and expected**; not a conflict. Only Blender etc. must avoid 9876.
- sketchup-mcp2 is primary for modeling; Hueflow is supplement/fallback. Never send geometry writes to both servers concurrently; reads in parallel are fine. mcp2 = mm, Hueflow = model units (check get_model_info).
- If 8080 accepts but never answers, Hueflow hung the Ruby timer and mcp2 may also stall: ask the user to save and restart SketchUp. Full rules: Drive guideline 26_Hueflow_mcp2_동시구동_2026-10-27.md.
