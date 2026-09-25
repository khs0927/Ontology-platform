"""Focused tests for atomicity, identity, and fail-closed behavior of the
release metadata generator.

Scope: scripts/generate-release-metadata.py. These tests cover what the
generator guarantees, not what any signing or verification step would
guarantee. Nothing here asserts that an artifact is signed or verified; the
generator is expected to keep reporting not_signed / verified=false.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-release-metadata.py"
spec = importlib.util.spec_from_file_location("release_metadata_atomicity", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SET_FILES = {"release-metadata.json", "provenance.json", "SHA256SUMS"}


def _make(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _sidecars(parent):
    return sorted(p.name for p in parent.iterdir() if p.name.startswith("."))


def _published(out):
    return sorted(p.name for p in out.iterdir())


# --- empty / zero artifact sets -------------------------------------------

def test_empty_artifact_set_fails_closed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="empty artifact set"):
        mod.generate(root, out, [])
    assert not out.exists()


def test_dry_run_of_empty_artifact_set_also_fails(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(mod.ReleaseMetadataError, match="empty artifact set"):
        mod.generate(root, root / "metadata", [], dry_run=True)


def test_zero_byte_artifact_is_still_a_recorded_artifact(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    empty = _make(root, "dist/placeholder-0.1.0-py3-none-any.whl", b"")
    result = mod.generate(root, root / "metadata", [empty])
    assert result["artifact_count"] == 1
    assert result["artifacts"][0]["size"] == 0
    assert result["artifacts"][0]["sha256"] == hashlib.sha256(b"").hexdigest()


def test_missing_input_is_rejected_instead_of_silently_skipped(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="not a regular file"):
        mod.generate(root, out, [root / "dist" / "absent.whl"])
    assert not out.exists()


# --- symlink inputs --------------------------------------------------------

@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform has no symlink")
def test_symlink_artifact_input_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    real = _make(root, "dist/real-1.0.whl", b"real bytes")
    link = root / "dist" / "link-1.0.whl"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation not permitted for this user")
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="refusing symlink"):
        mod.generate(root, out, [link])
    assert not out.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform has no symlink")
def test_symlink_detection_is_enforced_even_without_os_symlink_support(tmp_path, monkeypatch):
    """Covers the refusal on hosts where the test user cannot create links."""
    root = tmp_path / "repo"
    root.mkdir()
    sneaky = _make(root, "dist/sneaky-1.0.whl", b"pretending to be a link")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink",
                        lambda self: self.name == "sneaky-1.0.whl" or original(self))
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="refusing symlink"):
        mod.generate(root, out, [sneaky])
    assert not out.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform has no symlink")
def test_symlink_swapped_in_after_snapshot_is_caught_by_recheck(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    real = _make(root, "dist/real-1.0.whl", b"real bytes")
    link = root / "dist" / "link-1.0.whl"
    try:
        link.symlink_to(_make(root, "dist/other-1.0.whl", b"other bytes"))
    except OSError:
        pytest.skip("symlink creation not permitted for this user")
    original = mod._build_staged_set

    def swap(staging, records, data, build_root, sbom_requested):
        original(staging, records, data, build_root, sbom_requested)
        link.unlink()
        link.symlink_to(real)

    monkeypatch.setattr(mod, "_build_staged_set", swap)
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="refusing symlink"):
        mod.generate(root, out, [link])
    assert not out.exists()
    assert _sidecars(root) == []


# --- identity and basename collision --------------------------------------

def test_records_carry_digest_and_release_relative_identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0-py3-none-any.whl", b"wheel bytes")
    sdist = _make(root, "dist/demo-1.0.tar.gz", b"source bytes")
    result = mod.generate(root, root / "metadata", [wheel, sdist])
    by_name = {r["name"]: r for r in result["artifacts"]}
    assert by_name[wheel.name]["relative_name"] == "dist/demo-1.0-py3-none-any.whl"
    assert by_name[sdist.name]["relative_name"] == "dist/demo-1.0.tar.gz"
    for record in result["artifacts"]:
        assert record["identity"] == f"{record['sha256']}/{record['relative_name']}"
    assert len({r["identity"] for r in result["artifacts"]}) == 2
    assert result["artifacts"] == sorted(result["artifacts"], key=lambda r: r["identity"])


def test_basename_collision_across_directories_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    first = _make(root, "dist/a/demo-1.0.whl", b"build one")
    second = _make(root, "dist/b/demo-1.0.whl", b"build two")
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="basename collision"):
        mod.generate(root, out, [first, second])
    assert not out.exists()


def test_identical_input_listed_twice_is_one_artifact(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    result = mod.generate(root, root / "metadata", [wheel, wheel])
    assert result["artifact_count"] == 1


def test_artifact_outside_release_root_keeps_working_without_absolute_identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "demo-1.0.whl"
    outside.parent.mkdir()
    outside.write_bytes(b"external bytes")
    result = mod.generate(root, root / "metadata", [outside])
    record = result["artifacts"][0]
    assert "relative_name" not in record
    assert record["identity"] == f"{record['sha256']}/{record['name']}"
    assert str(tmp_path) not in json.dumps(result)


def test_artifact_inside_output_directory_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    out = root / "metadata"
    out.mkdir()
    stray = out / "stray.whl"
    stray.write_bytes(b"stray")
    with pytest.raises(mod.ReleaseMetadataError, match="describe itself"):
        mod.generate(root, out, [stray])


def test_serialized_metadata_never_contains_an_absolute_input_location(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    for name in SET_FILES:
        text = (out / name).read_text(encoding="utf-8")
        assert str(root) not in text
        assert str(tmp_path) not in text


# --- atomic set commit -----------------------------------------------------

def test_whole_set_is_published_and_nothing_is_left_behind(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    sdist = _make(root, "dist/demo-1.0.tar.gz", b"source bytes")
    out = root / "metadata"
    result = mod.generate(root, out, [wheel, sdist])
    assert _published(out) == sorted(SET_FILES)
    assert _sidecars(root) == []
    on_disk = json.loads((out / "release-metadata.json").read_text(encoding="utf-8"))
    assert on_disk == result
    sums = (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert sums == [f"{r['sha256']}  {r['relative_name']}" for r in result["artifacts"]]


def test_provenance_and_metadata_stay_unsigned_and_unverified(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    metadata = json.loads((out / "release-metadata.json").read_text(encoding="utf-8"))
    assert provenance["artifact_count"] == metadata["artifact_count"] == 1
    assert provenance["metadata_sha256"] == hashlib.sha256(
        (out / "release-metadata.json").read_bytes()).hexdigest()
    assert provenance["signature_status"] == "not_signed"
    assert provenance["verified"] is False
    assert metadata["signature_status"] == "not_signed"
    assert metadata["verified"] is False
    body = json.dumps(provenance).lower() + json.dumps(metadata).lower()
    for overclaim in ("signed\": true", "verified\": true", "signature_status\": \"signed"):
        assert overclaim not in body


def test_repeated_runs_are_deterministic_and_replace_the_set(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    first = mod.generate(root, out, [wheel])
    first_bytes = (out / "release-metadata.json").read_bytes()
    second = mod.generate(root, out, [wheel])
    assert first == second
    assert (out / "release-metadata.json").read_bytes() == first_bytes
    assert _published(out) == sorted(SET_FILES)
    assert _sidecars(root) == []


def test_unrelated_file_in_existing_output_set_is_not_carried_forward(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    out = root / "metadata"
    out.mkdir()
    (out / "leftover.json").write_text("{}", encoding="utf-8")
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    mod.generate(root, out, [wheel])
    assert _published(out) == sorted(SET_FILES)


def test_sbom_blocked_is_recorded_without_inventing_a_file(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    out = root / "metadata"
    result = mod.generate(root, out, [wheel], sbom_requested=True)
    assert result["sbom"] == {
        "status": "blocked",
        "blocker": "cyclonedx-bom and syft executables are not available",
    }
    assert _published(out) == sorted(SET_FILES)
    assert _sidecars(root) == []


# --- post-write races ------------------------------------------------------

def test_race_during_staging_publishes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    original = mod._build_staged_set

    def mutate(staging, records, data, build_root, sbom_requested):
        original(staging, records, data, build_root, sbom_requested)
        wheel.write_bytes(b"rebuilt during metadata generation")

    monkeypatch.setattr(mod, "_build_staged_set", mutate)
    out = root / "metadata"
    with pytest.raises(mod.ReleaseMetadataError, match="changed during"):
        mod.generate(root, out, [wheel])
    assert not out.exists()
    assert _sidecars(root) == []


def test_race_after_commit_restores_the_previous_set_when_it_still_matches(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    first = mod.generate(root, out, [wheel])
    before = (out / "release-metadata.json").read_bytes()

    original_recheck = mod.recheck

    def failing_recheck(observed, phase):
        if phase == "after":
            raise mod.ReleaseMetadataError(f"artifact changed {phase} metadata generation")
        original_recheck(observed, phase)

    monkeypatch.setattr(mod, "recheck", failing_recheck)
    with pytest.raises(mod.ReleaseMetadataError, match="changed after"):
        mod.generate(root, out, [wheel])
    assert (out / "release-metadata.json").read_bytes() == before
    assert json.loads(before.decode("utf-8")) == first
    assert _published(out) == sorted(SET_FILES)
    assert _sidecars(root) == []


def test_race_after_commit_leaves_no_metadata_when_the_old_set_is_also_stale(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    original_publish = mod._publish

    def publish_then_mutate(staging, output_dir):
        backup = original_publish(staging, output_dir)
        wheel.write_bytes(b"changed right after the commit")
        return backup

    monkeypatch.setattr(mod, "_publish", publish_then_mutate)
    with pytest.raises(mod.ReleaseMetadataError, match="changed after"):
        mod.generate(root, out, [wheel])
    assert not out.exists()
    assert _sidecars(root) == []


def test_artifact_deleted_after_commit_leaves_no_metadata(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    original_publish = mod._publish

    def publish_then_delete(staging, output_dir):
        backup = original_publish(staging, output_dir)
        wheel.unlink()
        return backup

    monkeypatch.setattr(mod, "_publish", publish_then_delete)
    with pytest.raises(mod.ReleaseMetadataError, match="not a regular file"):
        mod.generate(root, out, [wheel])
    assert not out.exists()
    assert _sidecars(root) == []


def test_failure_before_commit_leaves_a_previous_set_untouched(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    before = (out / "release-metadata.json").read_bytes()

    def explode(staging, records, data, build_root, sbom_requested):
        raise OSError("staging write failed")

    monkeypatch.setattr(mod, "_build_staged_set", explode)
    with pytest.raises(OSError):
        mod.generate(root, out, [wheel])
    assert (out / "release-metadata.json").read_bytes() == before
    assert _sidecars(root) == []


# --- CLI -------------------------------------------------------------------

def test_cli_exits_nonzero_on_a_refused_input(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                           "--output-dir", str(root / "metadata")],
                          capture_output=True, text=True)
    assert done.returncode == 2
    assert "empty artifact set" in done.stderr
    assert not (root / "metadata").exists()


def test_cli_publishes_a_set_and_prints_the_same_records(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    wheel = _make(root, "dist/demo-1.0.whl", b"wheel bytes")
    out = root / "metadata"
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                           "--output-dir", str(out), "--artifact", str(wheel)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == json.loads(
        (out / "release-metadata.json").read_text(encoding="utf-8"))
    assert _published(out) == sorted(SET_FILES)
