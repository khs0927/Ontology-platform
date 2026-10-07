# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['scripts/run_agent_bridge.py'],
    pathex=['apps/api', 'packages/core', 'packages/ingestion', 'packages/cad', 'packages/bim', 'packages/cair', 'packages/drive-store'],
    binaries=[],
    datas=[],
    hiddenimports=['sion_api', 'sion_api.db', 'sion_api.models', 'sion_api.repository', 'sion_ingestion', 'sion_ingestion.agent_bridge', 'sion_ingestion.map_import', 'sqlalchemy', 'pydantic'],
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
    name='sion-agent-bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
