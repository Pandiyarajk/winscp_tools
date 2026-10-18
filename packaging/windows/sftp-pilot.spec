# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: one folder holding sftp-pilot.exe (console) and
# sftp-pilot-gui.exe (no console window) that share all libraries.
#
# Author: Pandiyaraj Karuppasamy
# Date: Oct-18-2026
import pathlib

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = pathlib.Path(SPECPATH).resolve().parents[1]
here = pathlib.Path(SPECPATH).resolve()

datas = [(str(root / "sftp_pilot" / "example_config.ini"), "sftp_pilot")]
# The keyring finds its backends through package metadata, which PyInstaller
# does not copy on its own. Without these the exe cannot see Credential Manager.
datas += copy_metadata("keyring")
hiddenimports = collect_submodules("keyring.backends") + collect_submodules("win32ctypes")

excludes = ["pytest", "asyncssh", "pyflakes", "unittest", "pydoc", "test"]

a_cli = Analysis([str(here / "entry_cli.py")], pathex=[str(root)], datas=datas,
                 hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
a_gui = Analysis([str(here / "entry_gui.py")], pathex=[str(root)], datas=datas,
                 hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
MERGE((a_cli, "entry_cli", "sftp-pilot"), (a_gui, "entry_gui", "sftp-pilot-gui"))

pyz_cli = PYZ(a_cli.pure)
pyz_gui = PYZ(a_gui.pure)

exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="sftp-pilot",
              console=True, debug=False, strip=False, upx=False)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="sftp-pilot-gui",
              console=False, debug=False, strip=False, upx=False)

COLLECT(exe_cli, a_cli.binaries, a_cli.datas,
        exe_gui, a_gui.binaries, a_gui.datas,
        strip=False, upx=False, name="sftp-pilot")
