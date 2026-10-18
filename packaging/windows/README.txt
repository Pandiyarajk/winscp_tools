SFTP Pilot for Windows (no Python needed)
==========================================

1. Extract this whole zip to a folder.
2. In that folder run:   powershell -ExecutionPolicy Bypass -File install.ps1
3. Edit your server details:   notepad "%APPDATA%\SFTP Pilot\config.ini"
4. Start "SFTP Pilot" from the Start menu.

Two programs are installed:
  sftp-pilot-gui.exe   the window (no console)
  sftp-pilot.exe       the command line: --run-due, --history, --console,
                       --store-password, --version, --help

To run scheduled tasks while the window is closed (or after a reboot):
  powershell -ExecutionPolicy Bypass -File register-task.ps1

To remove everything:
  powershell -ExecutionPolicy Bypass -File uninstall.ps1
(your settings are kept unless you add -RemoveData)

Windows may show "Windows protected your PC" the first time, because this
program is not code-signed. Choose "More info", then "Run anyway", only if you
downloaded it from the project's GitHub releases page and the SHA256 shown
there matches:   Get-FileHash <the zip> -Algorithm SHA256

Some antivirus products dislike programs built with PyInstaller. The full
source is at https://github.com/Pandiyarajk/sftp-pilot and
`pip install sftp-pilot` installs the same program from PyPI.

WARNING: this tool uploads, overwrites and deletes files on remote servers,
including unattended through the scheduler. It is provided AS IS, without
warranty of any kind, and you use it entirely at your own risk. See
DISCLAIMER.md; LICENSE is the governing text.
