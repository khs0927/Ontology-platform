# aec-assets-mcp
Free CC0 architecture assets for SketchUp 2026 via MCP (FastMCP, mcp~=1.20).
Tools: search_polyhaven, download_polyhaven, search_ambientcg, download_ambientcg, import_into_sketchup (gltf/glb/obj -> decimated PolygonMesh with UV+texture via Hueflow :8080; .skp native), apply_texture_material.
Assets land in C:\Users\khs09\AEC-Assets. Poly Haven asks for visible credit when used via API. Keep max_faces <= ~20000 (430k-face import hung SketchUp).
Run: uv run --directory C:\CODE\aec-assets-mcp aec-assets-mcp ; tests: uv run pytest
