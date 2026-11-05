# 로컬 MCP 도구 카탈로그

로컬 PC의 MCP 서버가 2026-10-08(KST)에 보고한 도구 수와, 확인된 도구 이름입니다. 전체 스키마 덤프(수 MB)는
커밋하지 않고, 필요할 때 브리지로 다시 받습니다:
`node mcp-call.mjs tools <server> --out tools-<server>.json`.
여기에 없는 도구 이름은 추측하지 말고 위 명령으로 확인합니다.

## 서버별 요약

| 서버 | 도구 수 | 확인된 도구 이름 | 비고 |
|---|---|---|---|
| `sketchup-mcp2` | 22 | 아래 전체 목록 | MCP Server for SketchUp 1.30.0, 단위 mm |
| `hueflow-sketchup` | 21 | 아래 전체 목록 | sketchup-mcp 1.30.0, 단위는 모델 단위(미터법 아니면 inch) |
| `horizun-revit` | 111 | `horizun_health` | horizun-mcp.exe 2.1.5, Revit add-in 필요 |
| `autocad-mcp` | 2 | `search_tools`, `call_tool` | AutoCAD MCP Pro 3.4.7, 검색 후 호출 |
| `power-cad` (claude) | 19 | `cad_status`, `cad_list_targets` | 0.3.0 |
| `codex:power-cad` | 27 | `cad_list_targets` | 0.4.0, `--target autocad-2027-<pid>` |
| `multiCAD-mcp` | 7 | – | cwd `C:\CODE\multiCAD-mcp` |
| `xicad-headless` | 938 | – | ZWCAD, 항상 `--brief`/`--out` |
| `freecad-mcp` | 49 | – | |
| `rhino-ai` | 38 | – | |
| `grasshopper-ai` | 15 | – | |
| `korean-law` | 10 | – | 첫 기동 느림 |
| `korean-land` | 8 | – | |
| `kordoc` | 17 | – | |
| `jev` | 7 | `jev_decide`, `jev_noul`, `jev_verify`, `jev_screen`, `jev_classify`, `jev_rerank`, `jev_tool_route` | [`tools/jev-mcp`](../../tools/jev-mcp/README.md) |
| `sketchup` (cursor) | – | – | 고장: `sketchup_mcp` 모듈 없음 |
| `revit-mcp` | – | – | 고장: `C:\CODE\revit-mcp` 없음 |

## sketchup-mcp2 (22)

출처: `tools cursor:sketchup-mcp2` 결과. 모든 길이는 mm, 각도는 degree. 도구 호출 하나가 Undo 한 단계.

| 도구 | 설명(서버 원문 첫 문장) | 인자 |
|---|---|---|
| `create_component` | Create a primitive (cube / cylinder / cone / sphere) in SketchUp. | `type`, `position`, `dimensions`, `name` |
| `delete_component` | Delete a group or component by entity ID. | `id` |
| `transform_component` | Move, rotate and/or scale a group or component (mm / degrees). | `id`, `position`, `rotation`, `scale` |
| `get_selection` | Get the entities currently selected in the SketchUp UI. | – |
| `set_material` | Assign a material (color) to a group or component. | `id`, `material` |
| `export_scene` | Export the current scene to a temp file on the SketchUp host. | `format` |
| `create_mortise_tenon` | Create a mortise-and-tenon joint between two boards. | `mortise_id`, `tenon_id`, `width`, `height`, `depth`, `offset_x`, `offset_y`, `offset_z` |
| `create_dovetail` | Create a dovetail joint between two boards. | `tail_id`, `pin_id`, `width`, `height`, `depth`, `angle`, `num_tails`, `offset_x`, `offset_y`, `offset_z` |
| `create_finger_joint` | Create a finger joint (box joint) between two boards. | `board1_id`, `board2_id`, `width`, `height`, `depth`, `num_fingers`, `offset_x`, `offset_y`, `offset_z` |
| `eval_ruby` | Evaluate arbitrary Ruby code in SketchUp. | `code` |
| `boolean_operation` | Perform a boolean operation (union / difference / intersection) on two solids. | `target_id`, `tool_id`, `operation`, `delete_originals` |
| `chamfer_edge` | Chamfer (bevel) edges of a group/component by ``distance`` mm. | `id`, `distance` |
| `fillet_edge` | Round (fillet) edges of a group/component by ``radius`` mm with ``segments`` arc segments. | `id`, `radius`, `segments` |
| `get_viewport_screenshot` | Capture the current SketchUp viewport; returns the PNG image plus a JSON text block {width, height, preset_used, style_used}. | `max_size`, `view_preset`, `zoom_extents`, `style`, `restore_view` |
| `get_model_info` | Get current SketchUp model info: file path, title, units, bounding box, entity count, layer list. | – |
| `list_components` | List groups and component instances in the model (paginated). | `recursive`, `max_depth`, `limit`, `offset`, `response_format` |
| `get_component_info` | Detailed info for a single group or component instance by entity ID. | `id` |
| `find_components` | Find components matching name substring, layer, and/or type. | `name`, `layer`, `type`, `max_depth`, `limit`, `offset`, `response_format` |
| `list_layers` | List all model layers (tags). | – |
| `create_layer` | Create a new layer (tag) with the given name. | `name` |
| `undo` | Undo the last atomic operation in SketchUp. | – |
| `get_version` | Return the server version and Python↔Ruby compatibility verdict. | – |

## hueflow-sketchup (21)

출처: `tools claude:hueflow-sketchup` 결과. SketchUp에서 **Plugins > MCP Server > Start Server**(포트 8080) 후 사용.

| 도구 | 설명(서버 원문 첫 문장) | 인자 |
|---|---|---|
| `get_model_info` | Get general information about the currently open SketchUp model: name, file path, unit system, entity/layer/material counts. | – |
| `list_layers` | List all layers (tags) in the SketchUp model with their visibility. | – |
| `list_materials` | List all materials in the SketchUp model with their colors and textures. | – |
| `list_entities` | List entities (faces, edges, groups, component instances) in the model or inside a named group. | `group_name` |
| `list_components` | List all component definitions in the SketchUp model. | – |
| `create_face` | Create a flat face (polygon) in SketchUp from an ordered list of 3D points. | `points`, `layer`, `material` |
| `create_edge` | Create a line segment (edge) between two 3D points. | `start`, `end`, `layer` |
| `create_group` | Create an empty named group in SketchUp, optionally on a layer. | `name`, `layer` |
| `create_box` | Create a 3-D box (rectangular prism) by specifying width, depth, height. | `width`, `depth`, `height`, `origin`, `layer`, `material` |
| `create_circle` | Create a circle in SketchUp from a center point, normal vector, and radius. | `center`, `normal`, `radius`, `segments`, `layer`, `material` |
| `create_arc` | Create an arc in SketchUp. | `center`, `xaxis`, `normal`, `radius`, `start_angle`, `end_angle`, `segments`, `layer`, `material` |
| `create_polygon` | Create a regular polygon (triangle, pentagon, hexagon, etc.) with n sides. | `center`, `normal`, `radius`, `num_sides`, `inscribed`, `layer`, `material` |
| `push_pull` | Push/pull a face by a specified distance. | `entity_id`, `distance` |
| `follow_me` | Extrude a face along a path (array of edge IDs). | `face_id`, `path_ids` |
| `move_entity` | Move (translate) an entity by a vector [x, y, z]. | `entity_id`, `vector` |
| `rotate_entity` | Rotate an entity around an axis by a given angle in degrees. | `entity_id`, `axis_point`, `axis_vector`, `angle` |
| `scale_entity` | Scale an entity. | `entity_id`, `scale`, `origin` |
| `create_component` | Create a new (empty) component definition and place one instance in the model. | `name`, `description`, `origin` |
| `place_component` | Place an instance of an existing component definition into the model at a given origin. | `name`, `origin` |
| `create_roof_truss` | Create engineered roof trusses with accurate geometry based on professional truss analysis. | `span`, `pitch`, `type`, `count`, `spacing`, `overhang`, `lumber_size`, `origin`, `layer` |
| `execute_ruby` | Execute arbitrary Ruby code inside SketchUp. | `code` |
