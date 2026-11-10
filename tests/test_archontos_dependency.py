"""ArchOntos is a pinned dependency, never a vendored copy.

* Guard: no directory named ``archontos`` containing ``.py`` files may exist under
  ``packages/`` (that would be a re-vendored, drifting copy).
* Pin: the ``regulation`` extra pins ``archontos`` to one full commit SHA of
  khs0927/ArchOntos; uv.lock and docs/INTEGRATION_CONTRACTS.md agree with it, and the
  installed distribution (when present) was built from exactly that commit.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/khs0927/ArchOntos"
_PIN = re.compile(r"^archontos @ git\+" + re.escape(REPO_URL) + r"@(?P<sha>[0-9a-f]{40})\s*(;.*)?$")


def pinned_sha() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        extras = tomllib.load(fh)["project"]["optional-dependencies"]
    found = [m["sha"] for req in extras["regulation"] if (m := _PIN.match(req.strip()))]
    assert len(found) == 1, "regulation extra must pin archontos to exactly one full commit SHA"
    return found[0]


def test_no_vendored_archontos_under_packages() -> None:
    offenders = sorted(
        str(d.relative_to(ROOT))
        for d in (ROOT / "packages").rglob("archontos")
        if d.is_dir() and any(d.rglob("*.py"))
    )
    assert not offenders, f"ArchOntos must be a dependency, not a copy: {offenders}"


def test_pin_is_a_full_sha_on_the_regulation_extra() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", pinned_sha())


def test_uv_lock_matches_pin() -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    shas = set(re.findall(r'git = "' + re.escape(REPO_URL) + r'[^"#]*#([0-9a-f]{40})"', lock))
    assert shas == {pinned_sha()}, f"uv.lock resolves archontos to {shas}; run `uv lock`"


def test_integration_contracts_doc_names_pin() -> None:
    doc = (ROOT / "docs" / "INTEGRATION_CONTRACTS.md").read_text(encoding="utf-8")
    assert pinned_sha() in doc


def test_installed_archontos_matches_pin() -> None:
    try:
        dist = metadata.distribution("archontos")
    except metadata.PackageNotFoundError:
        pytest.skip("archontos not installed (install the 'regulation' extra)")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    commit = direct.get("vcs_info", {}).get("commit_id")
    if commit is None and os.getenv("SION_ARCHONTOS_LOCAL_OVERRIDE") == "1":
        pytest.skip(f"local archontos override in use: {direct.get('url')}")
    assert commit == pinned_sha(), (
        f"installed archontos is {commit or direct.get('url')}, pin is {pinned_sha()}; "
        "reinstall the regulation extra (or set SION_ARCHONTOS_LOCAL_OVERRIDE=1 for a local checkout)"
    )

    from archontos.db.migrate import packaged_migrations_dir
    from archontos.rules import engine  # noqa: F401  (the evaluator sion_api.regulation uses)

    migrations = packaged_migrations_dir()
    assert migrations is not None and any(migrations.glob("*.sql"))
