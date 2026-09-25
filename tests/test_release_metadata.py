"""Contract tests for the release metadata generator.

Scope: scripts/generate-release-metadata.py. These are oracles against the
production entry point. The generator is a supply-chain reporter, not a signer:
it must keep publishing ``not_signed`` / ``verified=false`` metadata, must
fail closed on an empty artifact set or on a dry run whose inputs vanished, and
must never leave a partial or stale set behind.

A failure here names a real production gap. It is fixed in the script, never
weakened here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-release-metadata.py"
spec = importlib.util.spec_from_file_location("release_metadata", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SET_FILES = {"release-metadata.json", "provenance.json", "SHA256SUMS"}


def _make(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _published(out):
    return sorted(p.name for p in out.iterdir())


def _sidecars(parent):
    return sorted(p.name for p in parent.iterdir() if p.name.startswith("."))


def _release_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


# --- determinism, identity, and the unsigned contract ---------------------

def test_release_metadata_is_deterministic_and_never_claims_signing(tmp_path):
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo-1.0-py3-none-any.whl", b"wheel bytes")
    before = hashlib.sha256(wheel.read_bytes()).hexdigest()

    a = mod.generate(root, tmp_path / "out1", [wheel])
    b = mod.generate(root, tmp_path / "out2", [wheel])

    assert a == b
    assert a["signature_status"] == "not_signed"
    assert a["verified"] is False
    assert a["schema_version"] == mod.SCHEMA_VERSION
    assert a["artifact_count"] == 1
    assert a["artifacts"] == [{
        "name": wheel.name,
        "sha256": before,
        "size": len(b"wheel bytes"),
        "relative_name": "dist/demo-1.0-py3-none-any.whl",
        "identity": f"{before}/dist/demo-1.0-py3-none-any.whl",
    }]
    # Observation is read-only: hashing must not disturb the input.
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == before

    # SHA256SUMS keys on the release-relative identity, not the basename.
    assert (tmp_path / "out1" / "SHA256SUMS").read_text(encoding="utf-8") == (
        f"{before}  dist/demo-1.0-py3-none-any.whl\n"
    )

    provenance = json.loads((tmp_path / "out1" / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == mod.SCHEMA_VERSION
    assert provenance["signature_status"] == "not_signed"
    assert provenance["verified"] is False
    assert provenance["artifact_count"] == 1
    assert provenance["metadata_sha256"] == hashlib.sha256(
        (tmp_path / "out1" / "release-metadata.json").read_bytes()
    ).hexdigest()


def test_records_are_ordered_by_identity_and_identities_are_unique(tmp_path):
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo-1.0-py3-none-any.whl", b"wheel bytes")
    sdist = _make(root, "dist/demo-1.0.tar.gz", b"source bytes")
    exe = _make(root, "dist/sion-agent-bridge.exe", b"binary bytes")

    result = mod.generate(root, root / "metadata", [exe, sdist, wheel])

    identities = [r["identity"] for r in result["artifacts"]]
    assert identities == sorted(identities)
    assert len(set(identities)) == 3
    for record in result["artifacts"]:
        assert record["identity"] == f"{record['sha256']}/{record['relative_name']}"
        assert record["relative_name"] == record["identity"].split("/", 1)[1]


def test_an_artifact_outside_the_release_root_never_leaks_an_absolute_path(tmp_path):
    root = _release_root(tmp_path)
    outside = tmp_path / "elsewhere" / "demo-1.0.whl"
    outside.parent.mkdir()
    outside.write_bytes(b"external bytes")

    result = mod.generate(root, root / "metadata", [outside])

    record = result["artifacts"][0]
    assert "relative_name" not in record
    assert record["identity"] == f"{record['sha256']}/{record['name']}"
    body = json.dumps(result)
    assert str(tmp_path) not in body
    assert str(root) not in body


# --- safe fields and dry run ----------------------------------------------

def test_metadata_contains_only_safe_artifact_fields_and_dry_run_writes_nothing(tmp_path):
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo.whl", b"x")

    result = mod.generate(root, root / "out", [wheel], dry_run=True)

    assert result["artifacts"][0].keys() == {
        "name", "sha256", "size", "relative_name", "identity"
    }
    assert not (root / "out").exists()
    assert _sidecars(root) == []
    for overclaim in ("credential", "environment", "secret", "token"):
        assert overclaim not in json.dumps(result).lower()


# --- empty / dry-run fail closed ------------------------------------------

def test_empty_artifact_set_fails_closed_in_a_dry_run(tmp_path):
    root = _release_root(tmp_path)
    out = root / "metadata"

    with pytest.raises(mod.ReleaseMetadataError, match="empty artifact set"):
        mod.generate(root, out, [], dry_run=True)

    assert not out.exists()
    assert _sidecars(root) == []


def test_empty_artifact_set_fails_closed_when_publishing(tmp_path):
    root = _release_root(tmp_path)
    out = root / "metadata"

    with pytest.raises(mod.ReleaseMetadataError, match="empty artifact set"):
        mod.generate(root, out, [])

    assert not out.exists()
    assert _sidecars(root) == []


def test_dry_run_still_fails_closed_when_an_input_disappears(tmp_path, monkeypatch):
    """A dry run reports on bytes; it must not describe a file that is gone."""
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo.whl", b"payload")
    original_recheck = mod.recheck

    def unlink_before_recheck(observed, phase):
        wheel.unlink()
        return original_recheck(observed, phase)

    monkeypatch.setattr(mod, "recheck", unlink_before_recheck)
    with pytest.raises(mod.ReleaseMetadataError, match="not a regular file"):
        mod.generate(root, root / "metadata", [wheel], dry_run=True)

    assert not (root / "metadata").exists()
    assert _sidecars(root) == []


# --- SBOM availability ----------------------------------------------------

def test_sbom_unavailable_is_recorded_as_blocked(tmp_path, monkeypatch):
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo.whl", b"payload")
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    out = root / "metadata"

    result = mod.generate(root, out, [wheel], sbom_requested=True)

    # The blocked verdict is only meaningful for a set that has artifacts, so
    # the run is driven with at least one real input.
    assert result["artifact_count"] == 1
    assert result["sbom"] == {
        "status": "blocked",
        "blocker": "cyclonedx-bom and syft executables are not available",
    }
    assert not (out / "sbom.json").exists()
    assert _published(out) == sorted(SET_FILES)
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["sbom"] == result["sbom"]
    assert _sidecars(root) == []


def test_sbom_request_fails_closed_on_an_empty_artifact_set(tmp_path, monkeypatch):
    root = _release_root(tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    out = root / "metadata"

    with pytest.raises(mod.ReleaseMetadataError, match="empty artifact set"):
        mod.generate(root, out, [], sbom_requested=True)

    assert not out.exists()
    assert not (out / "sbom.json").exists()
    assert _sidecars(root) == []


# --- unsigned / fail-closed atomicity -------------------------------------

def test_a_failed_run_never_leaves_a_partial_set_or_staging_scaffolding(tmp_path, monkeypatch):
    """A staging failure before the commit must not disturb the live set."""
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo.whl", b"payload")
    out = root / "metadata"
    mod.generate(root, out, [wheel])
    before = (out / "release-metadata.json").read_bytes()

    def explode(staging, records, data, build_root, sbom_requested):
        raise OSError("injected staging write failure")

    monkeypatch.setattr(mod, "_build_staged_set", explode)
    with pytest.raises(OSError):
        mod.generate(root, out, [wheel])

    assert (out / "release-metadata.json").read_bytes() == before
    assert _published(out) == sorted(SET_FILES)
    assert _sidecars(root) == []


def test_a_post_commit_change_drops_the_stale_set_instead_of_leaving_it_published(tmp_path, monkeypatch):
    root = _release_root(tmp_path)
    wheel = _make(root, "dist/demo.whl", b"payload")
    out = root / "metadata"
    original_recheck = mod.recheck

    def failing_recheck(observed, phase):
        if phase == "after":
            raise mod.ReleaseMetadataError(
                f"artifact changed {phase} metadata generation: demo.whl")
        return original_recheck(observed, phase)

    monkeypatch.setattr(mod, "recheck", failing_recheck)
    with pytest.raises(mod.ReleaseMetadataError, match="changed after"):
        mod.generate(root, out, [wheel])

    assert not out.exists()
    assert _sidecars(root) == []


# --- output path containment ----------------------------------------------

def test_safe_output_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        mod.safe_output(tmp_path / "out", "../escape.json")
    assert not (tmp_path / "escape.json").exists()
