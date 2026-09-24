"""Static security contracts for automation installers."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_windows_installer_uses_action_objects_and_never_reexecutes_shell_text():
    source = read("scripts/install-agent-sync.ps1")
    assert "Invoke-Expression" not in source
    assert "schtasks" not in source
    assert "New-ScheduledTaskAction" in source
    assert "Register-ScheduledTask" in source
    assert "[string[]]@($bridgeScript)" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "-ExecutionTimeLimit" in source
    assert "-RunLevel Limited" in source
    assert "Unregister-ScheduledTask" not in source
    assert "Initial sync failed with exit code" in source


def test_windows_sync_installer_is_collision_safe_and_checks_initial_exit():
    source = read("sync/install-windows.ps1")
    assert "Invoke-Expression" not in source
    assert "schtasks.exe" not in source
    assert "New-ScheduledTaskAction" in source
    assert "Register-ScheduledTask" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "-ExecutionTimeLimit" in source
    assert "-RunLevel Limited" in source
    assert "Unregister-ScheduledTask" not in source
    assert "refusing to modify or delete" in source
    assert "Initial backup failed with exit code" in source


def test_posix_installer_uses_managed_wrapper_and_propagates_failure():
    source = read("scripts/install-agent-sync.sh")
    assert "run-agent-sync.sh" in source
    assert "BEGIN sion-agent-sync managed" in source
    assert "END sion-agent-sync managed" in source
    assert "crontab" in source
    assert "Initial sync failed with exit code" in source
    assert "exit \"$INITIAL_EXIT\"" in source


def test_frozen_bridge_path_is_not_derived_from_meipass():
    # This contract guards the installer boundary without modifying run_agent_bridge.py.
    installer = read("scripts/install-agent-sync.ps1")
    sync_installer = read("sync/install-windows.ps1")
    assert "_MEIPASS" not in installer
    assert "_MEIPASS" not in sync_installer
