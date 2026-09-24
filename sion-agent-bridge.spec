# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

# PyInstaller defines SPECPATH for the directory containing this spec. Resolve
# once so checkout location and invocation directory do not affect the build.
ROOT = Path(SPECPATH).resolve()
API_ROOT = ROOT / "apps" / "api"
INGESTION_ROOT = ROOT / "packages" / "ingestion"
DRIVE_STORE_ROOT = ROOT / "packages" / "drive-store"

resource_files = sorted(
    p for p in (API_ROOT / "sion_api" / "resources").rglob("*") if p.is_file()
)
# Data is addressed exactly as importlib.resources.files("sion_api.resources")
# sees it in a frozen build, rather than preserving the checkout prefix.
datas = [
    (str(p), str(Path("sion_api") / "resources" / p.relative_to(API_ROOT / "sion_api" / "resources")))
    for p in resource_files
]

a = Analysis(
    [str(ROOT / "scripts" / "run_agent_bridge.py")],
    pathex=[str(API_ROOT), str(INGESTION_ROOT), str(DRIVE_STORE_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "sion_ingestion.bridge_cli",
        "sion_api",
        "sion_api.db",
        "sion_api.models",
        "sion_api.repository",
        "sion_api.resources",
        "sion_ingestion",
        "sion_ingestion.agent_bridge",
        "sion_ingestion.map_import",
        "sqlalchemy",
        "pydantic",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sion-agent-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
