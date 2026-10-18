"""
Windows packaging files: they are not built here (that needs PyInstaller and
takes minutes), but they must parse, stay plain ASCII, and the windowless
entry point must pick the right mode.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parent.parent / "packaging" / "windows"
SCRIPTS = ["build.ps1", "install.ps1", "uninstall.ps1", "register-task.ps1"]


def test_every_packaging_file_exists():
    for name in SCRIPTS + ["README.txt", "sftp-pilot.spec", "entry_cli.py", "entry_gui.py"]:
        assert (PACKAGING / name).is_file(), name


@pytest.mark.parametrize("name", SCRIPTS + ["README.txt"])
def test_scripts_are_plain_ascii(name):
    # Windows PowerShell 5.1 reads a BOM-less UTF-8 script as ANSI and garbles anything else.
    data = (PACKAGING / name).read_bytes()
    bad = sorted({b for b in data if b > 127})
    assert not bad, f"{name} has non-ASCII bytes {bad}"


@pytest.mark.skipif(not (shutil.which("powershell") or shutil.which("pwsh")), reason="no PowerShell")
@pytest.mark.parametrize("name", SCRIPTS)
def test_powershell_scripts_parse(name):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    assert exe
    path = str(PACKAGING / name)
    command = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{path}', [ref]$null, [ref]$e); if ($e) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")
    result = subprocess.run([exe, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_spec_is_valid_python():
    compile((PACKAGING / "sftp-pilot.spec").read_text(encoding="utf-8"), "sftp-pilot.spec", "exec")


def load_entry_gui():
    spec = importlib.util.spec_from_file_location("entry_gui", PACKAGING / "entry_gui.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv, expected", [
    ([], ["--gui"]),                                          # Start menu shortcut: open the window
    (["-c", "x.ini"], ["--gui", "-c", "x.ini"]),
    (["--run-due"], ["--run-due"]),                           # Task Scheduler: no window
    (["-c", "x.ini", "--run-due"], ["-c", "x.ini", "--run-due"]),
    (["--history", "5"], ["--history", "5"]),
    (["--init-config"], ["--init-config"]),
    (["--console"], ["--console"]),
    (["--store-password"], ["--store-password"]),
])
def test_windowless_exe_picks_the_mode(monkeypatch, argv, expected):
    entry = load_entry_gui()
    seen = {}
    import sftp_pilot.cli as cli
    monkeypatch.setattr(cli, "main", lambda args: seen.setdefault("args", args) and 0)
    monkeypatch.setattr(sys, "argv", ["sftp-pilot-gui.exe", *argv])
    assert entry.run() == 0
    assert seen["args"] == expected
