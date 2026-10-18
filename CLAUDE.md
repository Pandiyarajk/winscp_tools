# CLAUDE.md

Guidance for Claude Code in this repo. Global standards in
`C:\Users\pandi\.claude\CLAUDE.md` still apply.

## What this is

SFTP Pilot (`pip install sftp-pilot`): a paramiko based SFTP client with a
tkinter window, a console menu and a persistent scheduler, plus a Windows
program built with PyInstaller. Public repo: `Pandiyarajk/sftp-pilot`. It was
called WinSCP Manager (`winscp_tools`) up to 1.1.0 and does not use WinSCP.

## Layout

`sftp_pilot/`: `cli.py` (entry point, `--run-due`, `--history`, keyring
commands), `config_manager.py` (servers, env secrets, keyring), `sftp_handler.py`
(connection, atomic upload, folders and patterns), `scheduler.py` (schedules,
retries, file lock and claims, history), `runner.py`, `gui.py` + `theme.py` +
`scrollframe.py` + `remote_browser.py` (the window), `console.py`,
`keystore.py`. `packaging/windows/` builds the exe zip. `tests/` is pytest.

## Commands

```powershell
pip install -e ".[dev]"
python -m pytest -q -p no:cacheprovider        # about 300 tests, about a minute
python -m pyflakes sftp_pilot tests packaging
powershell -File packaging\windows\build.ps1   # dist\sftp-pilot-<version>-windows-x64.zip, about 4 minutes
```

## Rules that cost time when forgotten

- **The version lives only in `sftp_pilot/__init__.py`** (`pyproject.toml` reads it).
  Releasing: bump it, `CHANGE_LOG.md`, PR, merge, tag `vX.Y.Z`, `python -m build`,
  `twine check`, upload, build the zip from the merged commit, GitHub release with the
  zip, wheel, sdist and the zip's SHA256, then install it back from PyPI in a clean
  venv (the index can lag a minute or two). PyPI shows the README of the uploaded
  version, so a README fix needs a new version.
- **A named server never inherits credentials from `[DEFAULT]`** (`configparser`'s
  default section is switched off on purpose). Environment passwords are per server.
  Do not "simplify" either; a server that only changed its host would send another
  server's password.
- **A transfer never leaves a half-written file**: uploads go to `<name>.part` and
  are renamed; downloads use a local `.part`. `--run-due` exit codes are 0 (ok or
  nothing due), 1 (a task failed), 2 (config or lock error); Task Scheduler reports them.
- **Keyring is opt-in per server** (`password_store = keyring`) so an unattended run
  never waits on a locked keyring. `--store-password` checks the keyring exists
  BEFORE prompting.
- **The windowless exe (`sftp-pilot-gui.exe`) must accept `--run-due`** and the other
  modes; Task Scheduler uses it so no console window flashes.
- Paths in `config.ini` resolve against the config file's folder, never the
  working directory (Task Scheduler starts programs in System32).
- No em dashes or en dashes anywhere. Author header on new files, `Modified:` on edits.
  No `.github/workflows`. No `Co-Authored-By` trailers.

## Testing traps

- **GUI tests: one Tk root per module, `gc.disable()` for the module.** A new root per
  test lets the garbage collector finalise a dead root's variables on a worker thread,
  and that Tk call hangs without a mainloop. Use `shutdown()`, not `on_close()`, in tests.
- Keep test windows invisible (`attributes("-alpha", 0)` while mapped). Do not run the
  GUI tests while taking screenshots of the screen: they would be captured.
- Tk sometimes fails with "Can't find a usable tk.tcl" inside pytest on this machine;
  the GUI modules then skip with that reason. It never fails outside pytest.
- **Never undo a mutation test with `git checkout -- <file>`** when the file has
  uncommitted work; copy a backup and compare hashes.
- Bash heredoc Python patches mangle backslashes (`\n` became a real newline in an
  f-string). Put patches in a file written with the Write tool, or use the Edit tool.
- `test_two_processes_run_a_task_once` failed twice in whole-suite runs and never alone;
  it prints the failing process's output. The cause was not found.
- paramiko's `_prefetch_thread` can warn after a cancelled download when the channel
  closes. It is library noise.

## UI notes

Pack the status bar before the notebook or it is squeezed out. clam maps a smaller
padding onto the selected tab (override it). Size the window for the client area plus
`SCREEN_BOTTOM_MARGIN`, or the status bar slides under the taskbar on a 768 px screen.
Windows 5.1 PowerShell reads BOM-less UTF-8 scripts as ANSI, so keep the `.ps1` files
ASCII (a test checks it).
