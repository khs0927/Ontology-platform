from __future__ import annotations
import argparse, importlib.util, json, os
from pathlib import Path

spec=importlib.util.spec_from_file_location("sion_sync",Path(__file__).parents[1]/"sync"/"sion_sync.py")
sync=importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)

def args(src,drv,state,**kw):
 return argparse.Namespace(source=str(src),drive_root=str(drv),state_dir=str(state),device_id="dev",workspace_name="ws",**kw)

def test_backup_publishes_verified_v3_and_preserves_history(tmp_path):
 src=tmp_path/"src";src.mkdir();(src/"a.txt").write_text("one")
 drv=tmp_path/"drv";state=tmp_path/"state"
 assert sync.backup(args(src,drv,state))==0
 d=drv/"devices"/"dev"/"workspaces"/"ws"/"a.txt";assert d.read_text()=="one"
 (src/"a.txt").write_text("two");assert sync.backup(args(src,drv,state))==0
 assert d.read_text()=="two"
 assert list((drv/"history"/"dev").rglob("a.txt"))
 manifests=sorted((drv/"manifests"/"dev").glob("*.json")); body=json.loads(manifests[-1].read_text())
 assert body["schema"]=="sion-sync-manifest/v3" and body["verified_atomic"] is True

def test_destination_corruption_is_detected_and_repaired(tmp_path):
 src=tmp_path/"src";src.mkdir();(src/"a").write_text("good");drv=tmp_path/"drv";state=tmp_path/"state"
 sync.backup(args(src,drv,state));d=drv/"devices"/"dev"/"workspaces"/"ws"/"a";d.write_text("bad")
 assert sync.backup(args(src,drv,state))==0;assert d.read_text()=="good"

def test_partial_failure_does_not_advance_last_success(tmp_path,monkeypatch):
 src=tmp_path/"src";src.mkdir();(src/"a").write_text("good");drv=tmp_path/"drv";state=tmp_path/"state"
 sync.backup(args(src,drv,state));sp=state/"dev-ws.json";before=json.loads(sp.read_text())
 original=sync._atomic_copy
 def fail(*a,**k): raise OSError("injected")
 monkeypatch.setattr(sync,"_atomic_copy",fail)
 (src/"a").write_text("new");assert sync.backup(args(src,drv,state))==2
 after=json.loads(sp.read_text());assert after["attempts"]==2;assert after["last_success"]["run_id"]==before["last_success"]["run_id"];assert after["last_attempt"]["errors"]==1

def test_lock_rejects_concurrent_sync(tmp_path):
 lock=tmp_path/"lock"
 with sync.sync_lock(lock):
  rec=json.loads(lock.read_text());assert rec["pid"]>0 and rec["host"] and rec["created"]>0
  try: sync.sync_lock(lock).__enter__(); assert False
  except RuntimeError: pass

def test_stale_lock_is_reclaimed_only_after_timeout(tmp_path):
 lock=tmp_path/"lock";rec={"pid":999999999,"host":sync.os.environ.get("COMPUTERNAME") or sync.os.environ.get("HOSTNAME") or "unknown","created":sync.time.time()-1000};lock.write_text(json.dumps(rec))
 with sync.sync_lock(lock,timeout=1): pass
 assert not lock.exists()

def test_reparse_or_symlink_source_is_rejected(tmp_path):
 src=tmp_path/"src";src.mkdir();link=src/"link.txt"
 try: link.symlink_to(tmp_path/"target")
 except OSError: return
 with __import__("pytest").raises(OSError): list(sync.files_under(src))

def test_canonical_promote_uses_complete_marker(tmp_path):
 import subprocess
 repo=tmp_path/"repo";repo.mkdir();subprocess.run(["git","init"],cwd=repo,check=True,capture_output=True);(repo/"x").write_text("x");subprocess.run(["git","add","."],cwd=repo,check=True,capture_output=True);subprocess.run(["git","-c","user.name=t","-c","user.email=t@e","commit","-m","x"],cwd=repo,check=True,capture_output=True)
 drv=tmp_path/"drv";assert sync.promote(argparse.Namespace(project=str(repo),drive_root=str(drv),project_name="p"))==0
 snaps=list((drv/"canonical"/"p").glob("*/.complete"));assert snaps and not list((drv/"canonical"/"p").glob(".staging-*"))

def test_incomplete_existing_snapshot_is_repaired_and_quarantined(tmp_path):
 import subprocess
 repo=tmp_path/"repo";repo.mkdir();subprocess.run(["git","init"],cwd=repo,check=True,capture_output=True);(repo/"x").write_text("x");subprocess.run(["git","add","."],cwd=repo,check=True,capture_output=True);subprocess.run(["git","-c","user.name=t","-c","user.email=t@e","commit","-m","x"],cwd=repo,check=True,capture_output=True)
 info=sync.git_info(repo);drv=tmp_path/"drv";bad=drv/"canonical"/"p"/info["head"];bad.mkdir(parents=True);(bad/"_snapshot.json").write_text("{}")
 assert sync.promote(argparse.Namespace(project=str(repo),drive_root=str(drv),project_name="p"))==0
 assert (bad/".complete").is_file() and list((drv/"canonical"/"p").glob(".quarantine-*"))
