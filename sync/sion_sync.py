#!/usr/bin/env python3
from __future__ import annotations
import argparse, contextlib, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path
EXCLUDED_DIRS={".git","node_modules",".venv","venv","env","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache","dist","build",".next",".nuxt","out","target","bin","obj",".turbo",".cache",".parcel-cache",".idea",".vscode-test",".tools","coverage",".tox"}
EXCLUDED_NAMES={"Thumbs.db",".DS_Store","sync_history.log"}; EXCLUDED_SUFFIXES={".tmp",".temp",".swp",".swo",".pyc",".pyo",".db-wal",".db-shm",".sqlite-wal",".sqlite-shm"}
SECRET_PATTERNS=(re.compile(r"^\.env($|\.)",re.I),re.compile(r".*\.(pem|key|p12|pfx)$",re.I),re.compile(r"^(credentials|service-account).*\.json$",re.I))
def stamp(): return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
def safe_id(v):
 v=re.sub(r"[^A-Za-z0-9._-]+","-",v.strip()).strip("-").lower()
 if not v: raise ValueError("empty id")
 return v
def _reparse(p):
 try:return bool(p.lstat().st_file_attributes&0x400)
 except (AttributeError,OSError):return False
def _reject(p):
 if p.is_symlink() or _reparse(p):raise OSError(f"symlink/reparse point rejected: {p}")
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
def excluded(p):return p.name in EXCLUDED_NAMES or any(p.name.lower().endswith(s) for s in EXCLUDED_SUFFIXES) or any(x.match(p.name) for x in SECRET_PATTERNS)
def files_under(root):
 _reject(root)
 for base,dirs,names in os.walk(root,followlinks=False):
  dirs[:]=[d for d in dirs if d not in EXCLUDED_DIRS and not (Path(base)/d).is_symlink() and not _reparse(Path(base)/d)]
  for n in names:
   p=Path(base)/n
   if not excluded(p):_reject(p);yield p
def read_json(p,d):
 try:return json.loads(p.read_text(encoding="utf-8"))
 except Exception:return d
def _fsync_dir(p):
 if os.name!="nt":
  try:
   fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd)
  except OSError:pass
def write_json(p,data):
 p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=p.name+".",suffix=".tmp",dir=str(p.parent))
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
  os.replace(tmp,p);_fsync_dir(p.parent)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
@contextlib.contextmanager
def sync_lock(p, timeout=300.0):
 """Exclusive lock with conservative stale-owner recovery.

 The owner record is deliberately not treated as stale on a different host:
 PID namespaces and clock differences make that unsafe.
 """
 p.parent.mkdir(parents=True,exist_ok=True)
 host=os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"
 owner={"pid":os.getpid(),"host":host,"created":time.time()}
 while True:
  try:
   fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
   try:
    os.write(fd,json.dumps(owner,sort_keys=True).encode("utf-8"));os.fsync(fd)
   finally:os.close(fd)
   break
  except FileExistsError:
   try:
    rec=json.loads(p.read_text(encoding="utf-8"));same_host=rec.get("host")==host;pid=int(rec.get("pid",-1));age=time.time()-float(rec.get("created",0))
   except (OSError,ValueError,TypeError,json.JSONDecodeError):raise RuntimeError(f"invalid sync lock: {p}")
   alive=False
   if same_host and pid>0:
    if os.name=="nt":
     out=subprocess.run(["tasklist","/FI",f"PID eq {pid}"],capture_output=True,text=True).stdout
     alive=str(pid) in out and "No tasks" not in out
    else:
     try:os.kill(pid,0);alive=True
     except OSError:pass
   if same_host and not alive and age>timeout:
    try:os.unlink(p)
    except FileNotFoundError:pass
    continue
   raise RuntimeError(f"sync already running: {p}")
 try:yield
 finally:
  try:os.unlink(p)
  except FileNotFoundError:pass
def git_info(repo):
 if not(repo/".git").exists():return None
 def run(*a):return subprocess.check_output(["git","-C",str(repo),*a],stderr=subprocess.DEVNULL,text=True,encoding="utf-8").strip()
 try:return {"root":str(repo),"head":run("rev-parse","HEAD"),"branch":run("branch","--show-current"),"dirty":bool(run("status","--porcelain"))}
 except Exception:return {"root":str(repo),"error":"git metadata unavailable"}
def repos(root):
 if(root/".git").exists():
  x=git_info(root);return[x]if x else[]
 out=[]
 try:children=list(root.iterdir())
 except OSError:return out
 for p in children:
  if p.is_dir() and not p.is_symlink() and (p/".git").exists():
   x=git_info(p)
   if x:out.append(x)
 return out
def _safe_dest(d):
 c=d
 while True:
  if c.exists() and (c.is_symlink() or _reparse(c)):raise OSError(f"symlink/reparse point rejected: {c}")
  if c.parent==c:break
  c=c.parent
def _atomic_copy(src,dst):
 _reject(src);_safe_dest(dst);dst.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=dst.name+".",suffix=".tmp",dir=str(dst.parent))
 try:
  with os.fdopen(fd,"wb") as out,src.open("rb") as inp:
   for b in iter(lambda:inp.read(1048576),b""):out.write(b)
   out.flush();os.fsync(out.fileno())
  shutil.copystat(src,tmp);os.replace(tmp,dst);_fsync_dir(dst.parent)
 except:
  raise
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def backup(a):
 src=Path(a.source).expanduser().resolve();drv=Path(a.drive_root).expanduser().resolve()
 if not src.is_dir():raise SystemExit(f"source not found: {src}")
 drv.mkdir(parents=True,exist_ok=True);device=safe_id(a.device_id);workspace=safe_id(a.workspace_name);dest=drv/"devices"/device/"workspaces"/workspace;manifests=drv/"manifests"/device;history=drv/"history"/device
 state_dir=Path(a.state_dir).expanduser().resolve();state_dir.mkdir(parents=True,exist_ok=True);state_path=state_dir/f"{device}-{workspace}.json";run_id=uuid.uuid4().hex;ts=stamp()
 with sync_lock(drv/".sion-sync.lock"):
  old=read_json(state_path,{});old_files=old.get("last_success",{}).get("files",{});current={};changed=skipped=errors=0
  for p in files_under(src):
   try:
    rel=p.relative_to(src).as_posix();st=p.stat();digest=sha(p);d=dest/Path(rel);current[rel]={"size":st.st_size,"mtime_ns":st.st_mtime_ns,"sha256":digest}
    if d.exists() and not(d.is_symlink()or _reparse(d)) and sha(d)==digest:skipped+=1;continue
    if d.exists():
     _reject(d);h=history/ts/workspace/Path(rel);h.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(d,h)
    _atomic_copy(p,d)
    if sha(d)!=digest:raise OSError(f"destination verification failed: {rel}")
    changed+=1
   except Exception as e:errors+=1;print(f"[WARN] {p}: {e}",file=sys.stderr)
  m={"schema":"sion-sync-manifest/v3","verified_atomic":errors==0,"run_id":run_id,"timestamp_utc":ts,"device_id":device,"workspace":workspace,"source":str(src),"destination":str(dest),"mode":"one-way-non-destructive","changed":changed,"skipped":skipped,"errors":errors,"deleted_since_previous":sorted(set(old_files)-set(current)),"git_repositories":repos(src),"files":current};write_json(manifests/f"{ts}-{run_id}-{workspace}.json",m)
  state={"schema":"sion-sync-state/v3","run_id":run_id,"attempts":int(old.get("attempts",0))+1,"last_attempt":m}
  if errors==0:write_json(manifests/f"latest-{workspace}.json",m);state["last_success"]=m
  elif "last_success" in old:state["last_success"]=old["last_success"]
  write_json(state_path,state)
 print(json.dumps({k:m[k] for k in("timestamp_utc","device_id","workspace","changed","skipped","errors")}));return 0 if errors==0 else 2
def copy_filtered(src,dst):
 n=0
 for p in files_under(src):_atomic_copy(p,dst/p.relative_to(src));n+=1
 return n
def _valid_published_snapshot(dest,commit,project_name=None):
 try:
  if not dest.is_dir() or not (dest/".complete").is_file() or not (dest/"_snapshot.json").is_file():return False,None
  meta=read_json(dest/"_snapshot.json",None);complete=read_json(dest/".complete",None)
  if not isinstance(meta,dict) or not isinstance(complete,dict):return False,None
  if meta.get("schema")!="sion-canonical-snapshot/v3" or meta.get("git_sha")!=commit or complete.get("git_sha")!=commit:return False,None
  if not isinstance(meta.get("file_count"),int) or meta["file_count"]<0:return False,None
  if project_name and meta.get("project")!=project_name:return False,None
  if not complete.get("run_id") or not meta.get("timestamp_utc"):return False,None
  return True,meta
 except OSError:return False,None
def promote(a):
 project=Path(a.project).expanduser().resolve();drv=Path(a.drive_root).expanduser().resolve();info=git_info(project)
 if not info or info.get("error"):raise SystemExit("promote requires a readable Git repository")
 if info.get("dirty"):raise SystemExit("refusing promotion: Git working tree is dirty")
 name=safe_id(a.project_name or project.name);commit=info["head"];root=drv/"canonical"/name;dest=root/commit
 with sync_lock(root/".sion-sync.lock"):
  valid,old=_valid_published_snapshot(dest,commit,name)
  if valid:print(json.dumps({"status":"already-present","project":name,"git_sha":commit}));return 0
  root.mkdir(parents=True,exist_ok=True)
  if dest.exists():
   quarantine=root/f".quarantine-{uuid.uuid4().hex}";os.replace(dest,quarantine);print(json.dumps({"status":"quarantined-incomplete","path":str(quarantine)}),file=sys.stderr)
  staging=root/f".staging-{uuid.uuid4().hex}";staging.mkdir()
  try:
   count=copy_filtered(project,staging);run_id=uuid.uuid4().hex;meta={"schema":"sion-canonical-snapshot/v3","timestamp_utc":stamp(),"run_id":run_id,"project":name,"git_sha":commit,"branch":info.get("branch"),"file_count":count,"snapshot_path":str(dest)};write_json(staging/"_snapshot.json",meta);write_json(staging/".complete",{"run_id":run_id,"git_sha":commit,"created":meta["timestamp_utc"]});os.replace(staging,dest);_fsync_dir(root)
   try:write_json(root/"latest.json",{"status":"published","snapshot":str(dest),"git_sha":commit,"run_id":run_id})
   except Exception as e:raise RuntimeError(f"published snapshot but latest pointer update failed: {e}")
   print(json.dumps(meta));return 0
  finally:
   if staging.exists():shutil.rmtree(staging,ignore_errors=True)
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest="cmd",required=True);b=s.add_parser("backup");b.add_argument("--source",required=True);b.add_argument("--drive-root",required=True);b.add_argument("--device-id",required=True);b.add_argument("--workspace-name",default="C_CODE");b.add_argument("--state-dir",required=True);b.set_defaults(func=backup);c=s.add_parser("promote");c.add_argument("--project",required=True);c.add_argument("--drive-root",required=True);c.add_argument("--project-name");c.set_defaults(func=promote);a=p.parse_args();return a.func(a)
if __name__=="__main__":raise SystemExit(main())
