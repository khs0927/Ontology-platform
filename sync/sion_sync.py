#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {".git","node_modules",".venv","venv","env","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache","dist","build",".next",".nuxt","out","target","bin","obj",".turbo",".cache",".parcel-cache",".idea",".vscode-test",".tools","coverage",".tox"}
EXCLUDED_NAMES = {"Thumbs.db",".DS_Store","sync_history.log"}
EXCLUDED_SUFFIXES = {".tmp",".temp",".swp",".swo",".pyc",".pyo",".db-wal",".db-shm",".sqlite-wal",".sqlite-shm"}
SECRET_PATTERNS = (re.compile(r"^\.env($|\.)", re.I), re.compile(r".*\.(pem|key|p12|pfx)$", re.I), re.compile(r"^(credentials|service-account).*\.json$", re.I))

def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")

def safe_id(v):
    v = re.sub(r"[^A-Za-z0-9._-]+","-",v.strip()).strip("-").lower()
    if not v: raise ValueError("empty id")
    return v

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def excluded(path):
    n=path.name
    return n in EXCLUDED_NAMES or any(n.lower().endswith(s) for s in EXCLUDED_SUFFIXES) or any(p.match(n) for p in SECRET_PATTERNS)

def files_under(root):
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for n in names:
            p=Path(base)/n
            if not excluded(p): yield p

def read_json(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:
            json.dump(data,f,ensure_ascii=False,indent=2); f.write("\n")
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def git_info(repo):
    if not (repo/".git").exists(): return None
    def run(*a):
        return subprocess.check_output(["git","-C",str(repo),*a],stderr=subprocess.DEVNULL,text=True,encoding="utf-8").strip()
    try:
        return {"root":str(repo),"head":run("rev-parse","HEAD"),"branch":run("branch","--show-current"),"dirty":bool(run("status","--porcelain"))}
    except Exception:
        return {"root":str(repo),"error":"git metadata unavailable"}

def repos(root):
    if (root/".git").exists():
        x=git_info(root); return [x] if x else []
    out=[]
    try: children=list(root.iterdir())
    except OSError: return out
    for p in children:
        if p.is_dir() and (p/".git").exists():
            x=git_info(p)
            if x: out.append(x)
    return out

def backup(a):
    src=Path(a.source).expanduser().resolve()
    drv=Path(a.drive_root).expanduser().resolve()
    if not src.is_dir(): raise SystemExit(f"source not found: {src}")
    drv.mkdir(parents=True,exist_ok=True)
    device=safe_id(a.device_id); workspace=safe_id(a.workspace_name)
    dest=drv/"devices"/device/"workspaces"/workspace
    manifests=drv/"manifests"/device
    history=drv/"history"/device
    state_dir=Path(a.state_dir).expanduser().resolve(); state_dir.mkdir(parents=True,exist_ok=True)
    state_path=state_dir/f"{device}-{workspace}.json"
    old=read_json(state_path,{"files":{}}).get("files",{})
    current={}; changed=skipped=errors=0; ts=stamp()
    for p in files_under(src):
        try:
            rel=p.relative_to(src).as_posix(); st=p.stat(); prev=old.get(rel)
            local_same=bool(prev and prev.get("size")==st.st_size and prev.get("mtime_ns")==st.st_mtime_ns and prev.get("sha256"))
            digest=prev["sha256"] if local_same else sha(p)
            current[rel]={"size":st.st_size,"mtime_ns":st.st_mtime_ns,"sha256":digest}
            d=dest/Path(rel)
            if local_same and d.exists(): skipped+=1; continue
            d.parent.mkdir(parents=True,exist_ok=True)
            if d.exists():
                same=False
                try: same=d.stat().st_size==st.st_size and sha(d)==digest
                except OSError: pass
                if same: skipped+=1; continue
                h=history/ts/workspace/Path(rel); h.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(d,h)
            shutil.copy2(p,d); changed+=1
        except Exception as e:
            errors+=1; print(f"[WARN] {p}: {e}",file=sys.stderr)
    manifest={"schema":"sion-sync-manifest/v2","timestamp_utc":ts,"device_id":device,"workspace":workspace,"source":str(src),"destination":str(dest),"mode":"one-way-non-destructive","changed":changed,"skipped":skipped,"errors":errors,"deleted_since_previous":sorted(set(old)-set(current)),"git_repositories":repos(src),"files":current}
    write_json(manifests/f"{ts}-{workspace}.json",manifest)
    write_json(manifests/f"latest-{workspace}.json",manifest)
    write_json(state_path,{"files":current,"last_manifest":manifest})
    print(json.dumps({k:manifest[k] for k in ("timestamp_utc","device_id","workspace","changed","skipped","errors")},ensure_ascii=False))
    return 0 if errors==0 else 2

def copy_filtered(src,dst):
    n=0
    for p in files_under(src):
        d=dst/p.relative_to(src); d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,d); n+=1
    return n

def promote(a):
    project=Path(a.project).expanduser().resolve(); drv=Path(a.drive_root).expanduser().resolve()
    info=git_info(project)
    if not info or info.get("error"): raise SystemExit("promote requires a readable Git repository")
    if info.get("dirty"): raise SystemExit("refusing promotion: Git working tree is dirty")
    name=safe_id(a.project_name or project.name); commit=info["head"]; dest=drv/"canonical"/name/commit
    if dest.exists():
        print(json.dumps({"status":"already-present","project":name,"git_sha":commit})); return 0
    dest.mkdir(parents=True,exist_ok=False); count=copy_filtered(project,dest)
    meta={"schema":"sion-canonical-snapshot/v2","timestamp_utc":stamp(),"project":name,"git_sha":commit,"branch":info.get("branch"),"file_count":count,"snapshot_path":str(dest)}
    write_json(dest/"_snapshot.json",meta); write_json(drv/"canonical"/name/"latest.json",meta)
    print(json.dumps(meta,ensure_ascii=False)); return 0

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    b=s.add_parser("backup"); b.add_argument("--source",required=True); b.add_argument("--drive-root",required=True); b.add_argument("--device-id",required=True); b.add_argument("--workspace-name",default="C_CODE"); b.add_argument("--state-dir",required=True); b.set_defaults(func=backup)
    c=s.add_parser("promote"); c.add_argument("--project",required=True); c.add_argument("--drive-root",required=True); c.add_argument("--project-name"); c.set_defaults(func=promote)
    a=p.parse_args(); return a.func(a)
if __name__=="__main__": raise SystemExit(main())
