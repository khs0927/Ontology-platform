# 로컬 CAD/AEC MCP 운영 지침

Windows PC(예: `DESKTOP-CMFD3O8`)에 설치된 CAD/AEC MCP 서버를 에이전트가 안전하게 쓰기 위한 운영 규칙입니다.
대상 앱은 SketchUp, Revit(Horizun), AutoCAD, ZWCAD(xicad), FreeCAD, Rhino/Grasshopper이고, 한국 법령·토지·문서
서버(korean-law, korean-land, kordoc)와 jev도 같은 경로로 호출합니다. 호출 도구는
[`tools/grokbot-mcp-bridge`](../../tools/grokbot-mcp-bridge/README.md)이고, 절차는
[`skills/local-cad-mcp-bridge`](../../skills/local-cad-mcp-bridge/SKILL.md)에 있습니다.

> 이 문서의 서버 상태는 2026-10-08(KST) 점검 결과입니다. 상태는 바뀌므로 작업 전에 항상 다시 확인합니다.
> Sion 플랫폼 자체는 CAD를 변경하지 않습니다(`AGENTS.md`). 아래 규칙은 사용자의 요청으로 에이전트가 CAD 앱을
> 직접 조작할 때 적용됩니다.

## 핵심 규칙 요약

1. **상태 확인 먼저**: 앱 프로세스 → 플러그인 포트 → 읽기 전용 상태 도구 순서로 확인한 뒤에만 작업 도구를 호출합니다.
2. **스키마 확인**: 호출 전에 `tools <server> --out <file>`로 정확한 `inputSchema`를 확인합니다. 도구 이름을 추측하지 않습니다.
3. **파괴적 도구는 확인 후 실행**: 삭제·덮어쓰기·저장·불리언·임의 코드 실행(`eval_ruby`, `execute_ruby`, `call_tool`로 부르는 변경 도구)은 사용자에게 무엇을 바꾸는지 설명하고 명시적 승인을 받은 뒤에만 실행합니다.
4. **비밀값 출력 금지**: 설정 파일이나 환경 변수의 키를 출력·로그·커밋하지 않습니다(`servers` 명령은 자동으로 가립니다). [비밀값 취급 지침](SECRETS.ko.md) 참고.
5. **사용자 설정을 고치지 않기**: 실행 위치(cwd)·타임아웃 보정은 브리지의 `overrides.json`에만 넣습니다.

## 실행 환경

| 항목 | 값 |
|---|---|
| 브리지 위치 | `C:\Users\USER\grokbot-mcp-bridge\` (`mcp-call.mjs`, `README.md`, `overrides.json`, `test-results\`) |
| Node | `C:\Program Files\nodejs\node.exe` (Node 18 이상, v22에서 시험) |
| 설정 소스(읽기 전용) | `~\.cursor\mcp.json` → `%APPDATA%\Claude\claude_desktop_config.json` → `~\.codex\config.toml` → 수동(`horizun-revit`) |
| 이름 해석 | 이름만 쓰면 위 순서의 첫 항목. 다른 소스는 `source:name` (예: `codex:power-cad`, `claude:multiCAD-mcp`) |
| 종료 코드 | `0` 성공, `1` 브리지/기동 실패(`stage`, `stderrTail` 포함 JSON), `3` 도구가 `isError` 반환 |

```powershell
cd C:\Users\USER\grokbot-mcp-bridge
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs servers
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs tools <server> --brief --timeout 60000
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs tools <server> --out tools-<server>.json
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs call <server> <tool> --args-file args.json --timeout 120000
```

- PowerShell에서 `--args '<json>'`의 따옴표는 깨지기 쉬우므로 인자는 항상 JSON 파일로 만들고 `--args-file`을 씁니다.
- 한글이 깨지면 `[Console]::OutputEncoding`을 UTF-8로 설정하거나 `--out file.json` / `--ascii`를 씁니다.
- npx/uvx로 뜨는 서버(sketchup-mcp2, korean-law, kordoc)는 첫 기동에 30–150초가 걸릴 수 있습니다. `--timeout`을 늘립니다.

## 상태 확인 절차 (모든 작업 전에)

1. **앱 프로세스**
   ```powershell
   Get-Process SketchUp, Revit, acad, ZWCAD, Rhino, FreeCAD -ErrorAction SilentlyContinue |
     Select-Object Name, Id, MainWindowTitle
   ```
2. **플러그인 포트**(소켓형 플러그인만)
   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 8080, 9876 -ErrorAction SilentlyContinue |
     Select-Object LocalAddress, LocalPort, OwningProcess
   Test-NetConnection 127.0.0.1 -Port 9876 -InformationLevel Quiet
   ```
3. **읽기 전용 상태 도구** 호출: 아래 표의 "상태 확인 도구".
4. 실패하면 사용자에게 모델을 열고 플러그인 서버를 시작해 달라고 요청합니다. 임의로 앱을 재시작하거나 프로세스를 종료하지 않습니다(저장하지 않은 모델이 있을 수 있음).

## 서버별 전제 조건과 상태

| 서버 | 도구 수 | 앱/플러그인 전제 | 상태 확인 도구 | 2026-10-08 상태 |
|---|---|---|---|---|
| `sketchup-mcp2` | 22 | SketchUp 실행 + SketchUp 측 TCP 서버(MCPforSketchUp, `127.0.0.1:9876`, 추정) | `get_version`, `get_model_info` | 오전에는 도구 목록 정상, 13:50 KST `initialize`에서 멈춤 |
| `hueflow-sketchup` | 21 | SketchUp 플러그인 HTTP 포트 8080. SketchUp에서 **Plugins > MCP Server > Start Server** | `get_model_info` | 정상(플러그인 서버 시작 필요) |
| MCPforSketchUp | – | SketchUp 확장, 포트 9876 | 포트 확인 | 확장 설치됨 |
| `sketchup` (cursor) | – | Python 모듈 `sketchup_mcp` | – | **고장**: 모듈 없음 |
| `revit-mcp` | – | `C:\CODE\revit-mcp` 저장소 | – | **고장**: 경로 없음 |
| `horizun-revit` | 111 | `horizun-mcp.exe` 2.1.5 (`%LOCALAPPDATA%\Programs\Horizun\`) + Revit add-in. Revit 2024/2027이 `E:\Program files` 아래 설치됨 | `horizun_health` | 서버는 뜨지만 **Revit add-in 미배포** |
| `multiCAD-mcp` | 7 | cwd가 `C:\CODE\multiCAD-mcp`여야 함(`-m src.server`) | 도구 스키마 확인 후 읽기 도구 | `overrides.json`으로 cwd 보정 |
| `autocad-mcp` | 2 | AutoCAD MCP Pro 3.4.7, AutoCAD 2027에 COM 연결 | `search_tools` | 정상(AutoCAD 실행 필요) |
| `power-cad` (claude) | 19 | claude 항목 0.3.0 | `cad_status`, `cad_list_targets` | 정상 |
| `codex:power-cad` | 27 | codex 항목 0.4.0, 인자 `--target autocad-2027-<pid>` | `cad_list_targets` | AutoCAD 재시작 후 `<pid>`가 낡을 수 있음 |
| `xicad-headless` | 938 | ZWCAD | 도구 목록은 반드시 `--brief`/`--out` | 정상 |
| `freecad-mcp` | 49 | FreeCAD | 스키마 확인 후 읽기 도구 | 도구 목록 정상 |
| `rhino-ai` | 38 | Rhino | 스키마 확인 후 읽기 도구 | 도구 목록 정상 |
| `grasshopper-ai` | 15 | Rhino + Grasshopper | 스키마 확인 후 읽기 도구 | 도구 목록 정상 |
| `korean-law` | 10 | 없음(npx/uvx, 첫 기동 느림, timeout 150000) | – | 정상 |
| `korean-land` | 8 | 없음 | – | 정상 |
| `kordoc` | 17 | 없음(timeout 120000) | – | 정상 |
| `jev` | 7 | Node, 네트워크 | – | 정상([jev 지침](JEV-TYPESAFE.ko.md)) |

도구 이름 목록은 [도구 카탈로그](TOOL-CATALOG.ko.md)에 있습니다. 표에 없는 도구 이름은 반드시 `tools`로 확인한 뒤 씁니다.

## 안전 규칙: 확인이 필요한 도구

다음은 실행 전에 **무엇을, 어느 모델/도면에서, 되돌릴 수 있는지**를 사용자에게 말하고 승인을 받습니다.

| 분류 | 예 (실제 도구 이름) |
|---|---|
| 임의 코드 실행 | `sketchup-mcp2.eval_ruby`, `hueflow-sketchup.execute_ruby`, `autocad-mcp.call_tool`(변경 도구를 부를 때) |
| 삭제 | `sketchup-mcp2.delete_component`, `boolean_operation`(`delete_originals=true`) |
| 형상 변경 | `transform_component`, `move_entity`, `rotate_entity`, `scale_entity`, `push_pull`, `follow_me`, `chamfer_edge`, `fillet_edge` |
| 파일 출력·저장 | `sketchup-mcp2.export_scene`, 저장/내보내기 계열 도구 |

규칙:
- 사용자가 "읽기만" 요청했다면 변경 도구는 쓰지 않습니다. Ruby로 읽기 스크립트를 실행할 때도 코드 전문을 보여 주고 읽기 전용임을 밝힙니다(예: [`scripts/sketchup`](../../scripts/sketchup/README.md)의 덤프 스크립트).
- `eval_ruby`/`execute_ruby` 코드는 `model.start_operation` / `commit_operation`으로 묶어 한 번의 Undo로 되돌릴 수 있게 합니다. sketchup-mcp2는 도구 호출 하나가 Undo 한 단계입니다(`undo` 도구).
- 대량 변경 전에는 사용자가 모델을 저장(또는 사본 저장)했는지 확인합니다.
- jev 판단(`jev_screen` 등)은 참고 신호일 뿐 승인으로 쓰지 않습니다.

## 서버별 문제 해결

### sketchup-mcp2: `initialize`에서 멈춤
1. SketchUp이 실행 중이고 모델이 열려 있는지, 포트 9876이 LISTEN인지 확인합니다.
2. `overrides.json`에 이미 `timeout: 120000`이 있습니다(`cursor:`/`claude:sketchup-mcp2`, `codex:sketchup2`). uvx 첫 기동이면 한 번 더 기다립니다.
3. `--verbose`로 서버 stderr를 봅니다: `node mcp-call.mjs tools sketchup-mcp2 --verbose --timeout 150000`.
4. 이전 호출이 남긴 python/uvx 프로세스가 포트를 잡고 있으면 사용자 확인 후 정리합니다.
5. SketchUp 쪽 확장 서버를 다시 시작해 달라고 요청합니다.
6. 계속 실패하면 `hueflow-sketchup`으로 대체합니다(같은 모델, 다른 도구 집합·단위 주의).

### hueflow-sketchup: 연결 거부
- SketchUp 메뉴 **Plugins > MCP Server > Start Server**를 눌러야 포트 8080이 열립니다. SketchUp을 다시 켜면 다시 눌러야 합니다.
- `create_*` 도구의 좌표는 모델 단위(미터법이 아니면 인치)입니다. sketchup-mcp2(mm)와 섞어 쓰지 않습니다.

### `sketchup` (cursor 항목): `ModuleNotFoundError: sketchup_mcp`
- 항목이 가리키는 Python 환경에 `sketchup_mcp` 모듈이 없습니다. 사용자가 원하면 해당 패키지를 그 환경에 다시 설치하고, 아니면 이 항목은 쓰지 않고 `sketchup-mcp2`/`hueflow-sketchup`을 씁니다.
- 설정 수정이 필요하면 [클라이언트 동기화 지침](MCP-CLIENT-SYNC.ko.md)의 백업 절차를 먼저 따릅니다.

### revit-mcp: `C:\CODE\revit-mcp` 없음
- 저장소가 지워졌거나 옮겨졌습니다. 다시 받을지, 항목을 비활성화할지 사용자에게 묻습니다. Revit 작업은 `horizun-revit`을 우선합니다.

### horizun-revit: add-in 미배포
- `horizun-mcp.exe` 2.1.5는 뜨고 111개 도구를 나열하지만, 실제 호출은 Revit add-in이 Revit 안에서 실행 중이어야 합니다.
- Revit 2024/2027이 `E:\Program files` 아래에 있어 기본 경로를 가정하는 설치기가 add-in을 못 찾을 수 있습니다. Horizun 설치기/설정에서 대상 Revit 버전에 add-in을 배포하고(`.addin` 매니페스트가 해당 버전의 Addins 폴더에 있어야 함) Revit을 다시 시작한 뒤 `horizun_health`로 확인합니다.
- 브리지는 `%LOCALAPPDATA%\Programs\Horizun\**\horizun-mcp.exe`를 자동으로 찾습니다(수동 항목).

### multiCAD-mcp: 모듈을 못 찾음
- `-m src.server`는 저장소 루트에서만 동작합니다. `overrides.json`의 `"claude:multiCAD-mcp": { "cwd": "C:\\CODE\\multiCAD-mcp" }`가 있는지 확인합니다.

### autocad-mcp: 도구가 2개뿐
- 검색 모드 서버입니다. `search_tools`로 필요한 도구와 스키마를 찾은 뒤 `call_tool`로 부릅니다. AutoCAD 2027이 실행 중이어야 COM 호출이 됩니다.

### power-cad (codex): 대상 없음
- codex 항목의 `--target autocad-2027-<pid>`는 AutoCAD 프로세스 ID에 묶여 있어 재시작하면 낡습니다. `cad_list_targets`로 현재 대상을 확인하고, codex 설정의 `--target`을 갱신합니다(백업 후, [동기화 지침](MCP-CLIENT-SYNC.ko.md)).

### xicad-headless: 출력이 너무 큼
- 938개 도구라 전체 목록은 수 MB입니다. `--brief` 또는 `--out`을 쓰고, 필요한 도구만 스키마를 확인합니다.

### 공통: 기동 실패(exit 1)
- 출력 JSON의 `stage`(`resolve | spawn | initialize | tools/list | tools/call | args`)와 `stderrTail`을 봅니다.
- `resolve`: 이름 오타 또는 원격(`url`) 항목. 원격 항목은 브리지로 띄우지 않습니다.
- `spawn`: 명령 경로/PATH 문제. `.cmd` shim은 브리지가 `cmd.exe /d /s /c`로 감쌉니다.
- `initialize`: 앱/플러그인 미기동, 패키지 첫 설치 지연, 모듈 누락.

## 결과 기록

- 큰 결과는 `--out`으로 파일에 저장하고 요약만 보고합니다. 도구 전체 덤프(`test-results\`)는 저장소에 커밋하지 않습니다.
- GraphRAG에 넣을 모델 사실은 기존 SketchUp 자산 형식([`docs/SKETCHUP_KNOWLEDGE.md`](../SKETCHUP_KNOWLEDGE.md))을 따릅니다.
