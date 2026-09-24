import hashlib, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-release-metadata.py"
spec = importlib.util.spec_from_file_location("release_metadata", SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def test_release_metadata_is_deterministic_and_never_claims_signing(tmp_path):
    wheel = tmp_path / "dist" / "demo-1.0-py3-none-any.whl"; wheel.parent.mkdir()
    wheel.write_bytes(b"wheel bytes")
    before = hashlib.sha256(wheel.read_bytes()).hexdigest()
    a = mod.generate(ROOT, tmp_path / "out1", [wheel]); b = mod.generate(ROOT, tmp_path / "out2", [wheel])
    assert a == b
    assert a["provenance"]["signature_status"] == "not_signed"
    assert a["provenance"]["verified"] is False
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == before
    assert (tmp_path / "out1" / "SHA256SUMS").read_text().endswith("demo-1.0-py3-none-any.whl\n")

def test_release_metadata_contains_required_sections_and_safe_output(tmp_path):
    p = mod.generate(ROOT, tmp_path / "out", [])
    assert set(p) >= {"repository", "artifacts", "toolchain", "alembic_head", "resource_hashes", "provenance"}
    assert p["repository"]["git_dirty"] is not None
    assert p["alembic_head"] and p["resource_hashes"]
    assert p["provenance"]["signature_status"] == "not_signed"
    assert not (tmp_path / "out" / "../escape").exists()
    with __import__("pytest").raises(ValueError): mod.safe_output(tmp_path / "out", "../escape.json")
