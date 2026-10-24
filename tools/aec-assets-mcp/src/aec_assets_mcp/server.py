"""aec-assets-mcp: Poly Haven + ambientCG (CC0) -> SketchUp 2026."""
import io, json, os, zipfile, pathlib, httpx
from mcp.server.fastmcp import FastMCP

ROOT = pathlib.Path(os.environ.get("AEC_ASSETS_DIR", r"C:\Users\khs09\AEC-Assets"))
UA = {"User-Agent": "aec-assets-mcp/0.1 (khs0927; SketchUp asset helper)"}
HUEFLOW = os.environ.get("HUEFLOW_URL", "http://127.0.0.1:8080/ruby/execute")
mcp = FastMCP("aec-assets")

def _get(url, **kw):
    r = httpx.get(url, headers=UA, timeout=120, follow_redirects=True, **kw); r.raise_for_status(); return r

def _dl(url, dest: pathlib.Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists(): dest.write_bytes(_get(url).content)
    return str(dest)

@mcp.tool()
def search_polyhaven(type: str = "models", query: str = "", limit: int = 20) -> list:
    """Search Poly Haven (CC0). type: hdris|textures|models. Returns [{id,name,categories}]."""
    assets = _get("https://api.polyhaven.com/assets", params={"type": type}).json()
    q = query.lower().split()
    hits = [{"id": k, "name": v.get("name"), "categories": v.get("categories", [])}
            for k, v in assets.items()
            if all(t in (k + " " + v.get("name", "") + " " + " ".join(v.get("categories", []) + v.get("tags", []))).lower() for t in q)]
    return hits[:limit]

@mcp.tool()
def download_polyhaven(asset: str, res: str = "1k", format: str = "gltf") -> dict:
    """Download a Poly Haven asset to AEC-Assets/polyhaven/<asset>. format: gltf|fbx|blend (models), jpg|png (textures), hdr|exr (hdris).
    Models in gltf are also converted to OBJ for SketchUp import (key 'obj')."""
    files = _get(f"https://api.polyhaven.com/files/{asset}").json()
    out = ROOT / "polyhaven" / asset; res_out = {"asset": asset, "license": "CC0 (credit Poly Haven)", "files": []}
    if format in files and res in files[format]:  # model formats / hdri
        node = files[format][res]
        node = node.get(format, node) if isinstance(node, dict) and "url" not in node else node
        main = _dl(node["url"], out / pathlib.Path(node["url"]).name); res_out["main"] = main
        for rel, inc in (node.get("include") or {}).items(): _dl(inc["url"], out / rel)
        if format == "gltf": res_out["obj"] = to_obj(main)
    elif "hdri" in files and format in ("hdr", "exr"):
        node = files["hdri"][res][format]; res_out["main"] = _dl(node["url"], out / pathlib.Path(node["url"]).name)
    else:  # texture maps
        for mapname, v in files.items():
            if isinstance(v, dict) and res in v and format in v[res]:
                u = v[res][format]["url"]; res_out["files"].append(_dl(u, out / pathlib.Path(u).name))
    return res_out

def to_obj(gltf_path: str) -> str:
    import trimesh
    scene = trimesh.load(gltf_path, force="scene")
    objp = str(pathlib.Path(gltf_path).with_suffix(".obj"))
    if not os.path.exists(objp): scene.export(objp)  # writes .mtl + textures alongside
    return objp

@mcp.tool()
def search_ambientcg(query: str = "", type: str = "Material", limit: int = 20) -> list:
    """Search ambientCG (CC0). type: Material|HDRI|Decal|3DModel..."""
    j = _get("https://ambientcg.com/api/v2/full_json", params={"q": query, "type": type, "limit": limit, "include": "downloadData"}).json()
    return [{"id": a["assetId"], "name": a.get("displayName"), "downloads": [d["attribute"] for f in a.get("downloadFolders", {}).values() for c in f.get("downloadFiletypeCategories", {}).values() for d in c.get("downloads", [])]} for a in j.get("foundAssets", [])]

@mcp.tool()
def download_ambientcg(asset: str, attribute: str = "1K-JPG") -> dict:
    """Download+unzip an ambientCG asset (e.g. Bricks076, 1K-JPG) to AEC-Assets/ambientcg/<asset>. Returns maps incl. 'color'."""
    out = ROOT / "ambientcg" / asset / attribute
    if not out.exists():
        j = _get("https://ambientcg.com/api/v2/full_json", params={"id": asset, "include": "downloadData"}).json()["foundAssets"][0]
        link = next(d["downloadLink"] for f in j["downloadFolders"].values() for c in f["downloadFiletypeCategories"].values() for d in c["downloads"] if d["attribute"] == attribute)
        z = _get(link).content
        zipfile.ZipFile(io.BytesIO(z)).extractall(out)
    files = sorted(str(p) for p in out.iterdir())
    color = next((f for f in files if "_Color." in f), None)
    return {"asset": asset, "license": "CC0", "dir": str(out), "files": files, "color": color}

def ruby(code: str) -> dict:
    r = httpx.post(HUEFLOW, json={"code": code}, timeout=float(os.environ.get("HUEFLOW_TIMEOUT", "900"))); r.raise_for_status(); return r.json()

def _rq(s): return json.dumps(str(s).replace("\\", "/"))

def mesh_to_json(path: str, max_faces: int = 15000) -> str:
    """Convert any trimesh-readable model (gltf/glb/obj/fbx-less) to a JSON mesh bundle (metres, Z-up) for SketchUp."""
    import trimesh, numpy as np
    scene = trimesh.load(path, force="scene")
    out_dir = pathlib.Path(path).parent; parts = []
    for name, geom in scene.dump(concatenate=False) and [(g.metadata.get("name", f"part{i}"), g) for i, g in enumerate(scene.dump(concatenate=False))]:
        total = sum(len(g.faces) for g in scene.dump(concatenate=False))
        if total > max_faces and len(geom.faces) > 500:
            try:
                uvkeep = getattr(geom.visual, "uv", None) is not None
                dec = geom.simplify_quadric_decimation(face_count=max(200, int(len(geom.faces) * max_faces / total)))
                if uvkeep and getattr(dec.visual, "uv", None) is None:  # re-project UVs from nearest original vertex
                    from scipy.spatial import cKDTree
                    _, idx = cKDTree(geom.vertices).query(dec.vertices)
                    dec.visual = trimesh.visual.TextureVisuals(uv=np.asarray(geom.visual.uv)[idx], material=geom.visual.material)
                geom = dec
            except Exception as e:
                print("decimate failed", e, file=__import__("sys").stderr)
        v = np.asarray(geom.vertices, float)
        if path.lower().endswith((".gltf", ".glb")): v = v[:, [0, 2, 1]] * [1, -1, 1]  # Y-up -> Z-up
        tex = None; uv = None
        vis = getattr(geom, "visual", None)
        if vis is not None and getattr(vis, "kind", None) == "texture" and getattr(vis, "uv", None) is not None:
            uv = np.asarray(vis.uv, float).round(5).tolist()
            img = getattr(vis.material, "baseColorTexture", None) or getattr(vis.material, "image", None)
            if img is not None:
                tex = str(out_dir / f"_sk_{len(parts)}.png"); img.save(tex)
        parts.append({"v": v.round(5).tolist(), "f": np.asarray(geom.faces, int).tolist(), "uv": uv, "tex": tex})
    jp = str(pathlib.Path(path).with_suffix(f".{max_faces}.skmesh.json")); pathlib.Path(jp).write_text(json.dumps(parts)); return jp

@mcp.tool()
def import_into_sketchup(path: str, group_name: str = "GB_ASSET", x_m: float = 15.0, y_m: float = 0.0, z_m: float = 0.0, max_faces: int = 15000) -> dict:
    """Import a model into the open SketchUp model inside a named group at (x,y,z) metres.
    .skp is loaded natively; .gltf/.glb/.obj (e.g. Poly Haven) are meshed via trimesh -> PolygonMesh with UVs + base-color texture
    (SketchUp 2026 Ruby can't import glTF and OBJ import is UI-only)."""
    if path.lower().endswith(".skp"):
        body = f"d=m.definitions.load({_rq(path)}); g.entities.add_instance(d, Geom::Transformation.new)"
    else:
        jp = mesh_to_json(path, max_faces)
        body = f"""require 'json'; parts=JSON.parse(File.read({_rq(jp)}))
parts.each_with_index{{|p,k| pm=Geom::PolygonMesh.new(p['v'].size,p['f'].size)
 pts=p['v'].map{{|a| Geom::Point3d.new(a[0].m,a[1].m,a[2].m)}}; ix=pts.map{{|q| pm.add_point(q)}}
 p['f'].each{{|f| pm.add_polygon(ix[f[0]],ix[f[1]],ix[f[2]]) rescue nil}}
 mat=nil; if p['tex'] then mat=m.materials.add({_rq(group_name)}+'_'+k.to_s); mat.texture=p['tex'] end
 if p['uv'] then p['uv'].each_with_index{{|u,i| pm.set_uv(ix[i], Geom::Point3d.new(u[0],u[1],1), true)}} end
 g.entities.add_faces_from_mesh(pm, Geom::PolygonMesh::AUTO_SOFTEN|Geom::PolygonMesh::SMOOTH_SOFT_EDGES, mat, mat)}}"""
    code = f"""m=Sketchup.active_model; (m.abort_operation rescue nil); m.start_operation('aec import',true)
g=m.entities.add_group; g.name={_rq(group_name)}
{body}
g.transform!(Geom::Transformation.new(Geom::Point3d.new({x_m}.m,{y_m}.m,{z_m}.m)))
m.commit_operation; bb=g.bounds; [g.name, g.entities.grep(Sketchup::Face).size, bb.width.to_m.round(2), bb.depth.to_m.round(2), bb.height.to_m.round(2)].inspect"""
    return ruby(code)
@mcp.tool()
def apply_texture_material(path: str, name: str, size_m: float = 1.0, target_group: str = "") -> dict:
    """Create/update SketchUp material `name` from a color/albedo texture image (size_m tiling). Optionally paint all faces in group `target_group`."""
    code = f"""m=Sketchup.active_model; (m.abort_operation rescue nil); m.start_operation('aec mat',true)
mat=m.materials[{_rq(name)}]||m.materials.add({_rq(name)}); mat.texture={_rq(path)}; mat.texture.size={size_m}.m
n=0; if {_rq(target_group)}!='' then m.entities.grep(Sketchup::Group).select{{|g| g.name=={_rq(target_group)}}}.each{{|g| g.entities.grep(Sketchup::Face).each{{|f| f.material=mat; f.back_material=mat; n+=1}}}} end
m.commit_operation; [mat.name, n].inspect"""
    return ruby(code)

def main(): mcp.run()
if __name__ == "__main__": main()
