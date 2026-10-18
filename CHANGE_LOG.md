# Change Log

All notable changes to SFTP Pilot (formerly WinSCP Manager) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

**Repository:** [https://github.com/Pandiyarajk/sftp-pilot](https://github.com/Pandiyarajk/sftp-pilot)  
**Author:** Pandiyaraj Karuppasamy

---

## [2.2.0] - 2026-10-18

Usability: several servers, whole folders, a remote browser, trust and keyring.

### Added
- **Several servers:** `[server:<name>]` sections next to `[DEFAULT]`. The GUI
  (Connection and Scheduler tabs) and the console pick a server, each scheduled
  task remembers its server, `--run-due` connects each task to its own, and the
  history and task lists show it. Single-server configs and 2.1 task files load
  unchanged.
- **Folders and patterns:** upload or download a folder (recursively) or a
  pattern such as `*.csv`, in the GUI, the console and scheduled tasks. One bad
  file does not stop the others; the result reports `N of M failed`. Symbolic
  links are skipped, and a file name sent by a server that could point outside
  the destination is refused. Wildcard delete is deliberately not offered.
- **Remote file browser** (GUI): a Browse remote button beside every remote
  path, plus Folder buttons for local folders.
- **Host-key fingerprint prompt:** `host_key_policy = ask` shows the SHA256
  fingerprint of a new server and trusts it only on a yes. Scheduled and
  `--run-due` runs cannot ask and refuse unknown servers. `accept_new` now logs
  the fingerprint it trusted.
- **OS keyring (optional):** `pip install sftp-pilot[keyring]`,
  `sftp-pilot --store-password [--server NAME]`, then `password_store = keyring`
  in that server's section. Also `--store-passphrase` and `--forget-secrets`.
  Opt-in per server so an unattended run never waits on a locked keyring.
  Order of use: environment variable, keyring, file.

- **Windows program, no Python needed:** `sftp-pilot-gui.exe` (no console window)
  and `sftp-pilot.exe` from one PyInstaller build, shipped as a zip on the
  releases page with `install.ps1` (per user, no admin rights, Start menu
  shortcut, settings in `%APPDATA%\SFTP Pilot`), `register-task.ps1` (Task
  Scheduler job for `--run-due`, optionally when logged off), `uninstall.ps1`
  and `build.ps1`. Not code-signed: SmartScreen may warn. The windowless exe
  accepts `--run-due` and the other command-line modes, so a scheduled run
  never flashes a console window.

### Changed
- **A named server never inherits credentials from `[DEFAULT]`.** configparser's
  default inheritance is switched off, so a server that only changed its host
  cannot receive another server's password. `protocol`, `host_key_policy`,
  `known_hosts_file`, `timeout` and `atomic_uploads` are still shared.
- Environment passwords are per server: `SFTP_PILOT_PASSWORD` is for the default
  server only; a named server uses `SFTP_PILOT_PASSWORD_<NAME>`.
- Other sections (`[PATHS]`, `[SCHEDULING]`, `[LOGGING]`) no longer inherit keys
  from `[DEFAULT]`.
- When a password is configured and no key file, the SSH agent and `~/.ssh` keys
  are no longer offered first: it was slow, and servers with a low `MaxAuthTries`
  could refuse the login before the password was tried.
- API: `make_task_executor`'s callback now receives the task's server name;
  `SFTPHandler.upload()` and `download()` (file, folder or pattern) return a
  `BulkResult`; `ConfigManager.get_connection_details(server="")`.

---

## [2.1.0] - 2026-10-18

Safer transfers and unattended runs.

### Added
- **Atomic uploads:** files are uploaded to `<name>.part` and renamed into
  place (OpenSSH posix-rename; without it, the old file is moved aside and
  restored if the swap fails). A failed or cancelled upload leaves the previous
  version untouched. `atomic_uploads = false` turns it off.
- **Cancel** a transfer: Cancel button in the GUI, Ctrl+C in the console (which
  previously quit the app mid-transfer). Partial files are removed.
- **Retries** for scheduled tasks with doubling delays: `[SCHEDULING] retries`
  (default 3) and `retry_delay` (default 60 s).
- **`sftp-pilot --run-due`** for Windows Task Scheduler and cron. Exit codes 0
  (ok or nothing due), 1 (a task failed), 2 (config or tasks file unusable).
  Verified under real Task Scheduler and real cron.
- **Daily schedules** at a time of day, optionally on chosen weekdays.
- **Run history** (`scheduled_tasks.history.jsonl`, rotated at 5 MB): GUI
  History tab, console menu item 12, `sftp-pilot --history [N] [--task ID]`.

### Changed
- The tasks file is shared safely between processes: an inter-process lock
  around every change, and tasks are claimed before they run, so the GUI and
  `--run-due` never run the same task twice.
- Interval tasks run on a fixed grid from their first run instead of "N minutes
  after the last run finished", so they no longer drift; missed slots after
  downtime are skipped, not replayed.
- Relative paths in the config, and the default tasks file, resolve against the
  config file's folder instead of the current directory (Task Scheduler starts
  programs in `C:\Windows\System32`).
- A failed scheduled task records the real reason (for example
  `delete failed: No such file`) instead of "see log".
- Console: Exit moved to 13 (`q` also exits).
- `TaskScheduler.run_due_tasks()` returns the run records instead of a count.

### Notes
- File size is checked after every transfer by paramiko, as before. There is
  no checksum check: SFTP has no standard command for one.
- Task files from 2.0 load unchanged.

---

## [2.0.2] - 2026-10-18

### Fixed
- README links to the licence, disclaimer, changelog and config template were
  relative, so they were dead on the PyPI project page; they are absolute now.

---

## [2.0.1] - 2026-10-18

### Added
- `sftp-pilot --init-config` writes a starter `config.ini` (never overwrites).
  The template now ships inside the package, so a `pip install sftp-pilot`
  has one; before, it existed only in the source tree.

### Changed
- README quick start installs from PyPI.

---

## [2.0.0] - 2026-10-18

Renamed from **WinSCP Manager** to **SFTP Pilot**. The app never used WinSCP,
and WinSCP is another project's name. Behaviour is unchanged from 1.1.0.

### Changed (breaking)
| Was | Now |
| --- | --- |
| repository `winscp_tools` | `sftp-pilot` (GitHub redirects the old URL) |
| package `winscp_manager` | `sftp_pilot` |
| command `winscp-manager` | `sftp-pilot` |
| `python -m winscp_manager` | `python -m sftp_pilot` |
| class `WinSCPHandler` (`winscp_handler.py`) | `SFTPHandler` (`sftp_handler.py`) |
| env `WINSCP_MANAGER_PASSWORD` | `SFTP_PILOT_PASSWORD` |
| env `WINSCP_MANAGER_KEY_PASSPHRASE` | `SFTP_PILOT_KEY_PASSPHRASE` |
| default log file `winscp_manager.log` | `sftp_pilot.log` |

`config.ini`, `known_hosts` and `scheduled_tasks.json` keep their names and
format, so existing files carry over. If you set `log_file` explicitly, it is
kept as written.

---

## [1.1.0] - 2026-10-17

Review fixes. Several 1.0.0 entries below described behaviour the code did not
have; this release either implements it or says so.

### Fixed
- **Installed `winscp-manager` command crashed** with `ModuleNotFoundError: No
  module named 'main'`; the entry point is now `winscp_manager.cli:main`.
- **Host keys were never verified** (`AutoAddPolicy` accepted any server). The
  default is now `accept_new`: remember a server on first connect, refuse it if
  its key changes. `reject` and `auto_add` are available.
- Key authentication only accepted RSA keys and had no passphrase support;
  RSA, ECDSA and Ed25519 keys, encrypted or not, now work.
- Scheduled tasks ignored `private_key_path` and connected with the password
  only, and shared the GUI's SFTP connection across threads. Each run now opens
  its own connection from the config file.
- GUI worker threads updated widgets and opened dialogs directly, which Tk does
  not support. All UI updates now go through the main thread. Connect and
  delete no longer freeze the window.
- Console: pressing Enter at "task ID to remove" removed the first task; IDs
  now need four or more characters and must match exactly one task. Ctrl+C or
  end of input no longer crash it.
- A recurring task that failed once was never run again; it now keeps its
  schedule and records the error.
- A task running when the app closed stayed `running` forever; it is now
  rescheduled on the next start.
- `stop()` could take 10 seconds and tasks could be lost by concurrent saves;
  the task file is now written atomically under a lock.
- Progress callbacks divided by zero on empty files.
- A failed download left a truncated file; downloads now go to `.part` first.
- `config.ini` was committed despite being in `.gitignore`; it is untracked.

### Changed
- Python 3.11+ (3.7 to 3.10 are end of life). Packaging moved to
  `pyproject.toml`; unused `python-dateutil` and `pytz` dependencies dropped.
- `check_interval`, `enabled` and the `[LOGGING]` settings are now honoured.
- `--config` and `--tasks-file` options; `python -m winscp_manager` works.
- `WINSCP_MANAGER_PASSWORD` and `WINSCP_MANAGER_KEY_PASSPHRASE` environment
  variables override the config file.
- The `scp` protocol option was removed: it never existed (everything ran over
  SFTP). `protocol` must be `sftp`.
- The unused `temp_dir` setting was removed.

### Added
- Test suite, including integration tests against a local SFTP server.
- Disclaimer in the README, `DISCLAIMER.md`, and a warning in `--help`.

### Corrected claims from 1.0.0
- There is no automatic reconnection and no resume of interrupted transfers.
  Scheduled runs reconnect each time, which covers the unattended case.

---

## [1.0.0] - 2025-10-19

**Initial Release** - Complete feature set

### Added

#### Core Features
- **WinSCP/SFTP Protocol Handler**
  - Full SFTP protocol support using paramiko library
  - Connection management with automatic reconnection
  - Support for password and key-based authentication
  - Secure file transfer operations

#### File Operations
- **Upload Functionality**
  - Upload files of any size to remote server
  - Progress tracking with callback support
  - Automatic remote directory creation
  - Large file support with efficient streaming

- **Download Functionality**
  - Download files from remote server
  - Progress tracking and reporting
  - Automatic local directory creation
  - Resume capability for interrupted transfers

- **Delete Functionality**
  - Delete files from remote server
  - Safety confirmations in both interfaces
  - Batch delete support through scheduler

- **File Management**
  - List files in remote directories
  - Check file existence
  - Get file metadata

#### Scheduling System
- **Task Scheduler**
  - Background task execution engine
  - Support for three task types: Upload, Download, Delete
  - Persistent task storage (JSON-based)
  - Automatic task state management

- **Recurring Tasks**
  - Configure tasks to run at regular intervals
  - Customizable interval in minutes
  - Automatic rescheduling after execution

- **Task Management**
  - Add new scheduled tasks
  - View all scheduled tasks with details
  - Remove/cancel tasks
  - Task status tracking (pending, running, completed, failed)
  - Error logging for failed tasks

#### Configuration Management
- **Config File Support**
  - INI-based configuration file
  - Separate sections for connection, paths, scheduling, and logging
  - Easy credential management
  - Support for multiple authentication methods

- **Path Management**
  - Default remote upload directory
  - Default local download directory
  - Temporary file directory configuration

#### User Interfaces

##### GUI Interface (Tkinter)
- **Main Window**
  - Modern tabbed interface design
  - 1000x700 default window size
  - Status bar with connection status
  - Real-time updates

- **Connection Tab**
  - Server configuration form
  - Protocol selection (SFTP, SCP)
  - Connect/disconnect buttons
  - Load configuration from file
  - Visual connection status

- **File Operations Tab**
  - Upload section with file browser
  - Download section with save dialog
  - Delete section with confirmation
  - Progress bar for transfers
  - Real-time transfer statistics

- **Scheduler Tab**
  - Add scheduled task form
  - Task type selection dropdown
  - File browser integration
  - Recurring task configuration
  - Task list view (TreeView)
  - Start/stop scheduler controls
  - Refresh and remove task buttons

- **Logs Tab**
  - Scrollable log viewer
  - Real-time log updates
  - Formatted log entries with timestamps
  - Color-coded log levels

##### Console Interface
- **Interactive Menu System**
  - 12 menu options
  - Clear, numbered interface
  - Input validation
  - User-friendly prompts

- **All File Operations**
  - Upload with progress display
  - Download with progress display
  - Delete with confirmation
  - List remote files

- **Scheduler Management**
  - Schedule new tasks interactively
  - View all scheduled tasks
  - Remove tasks by ID
  - Start/stop scheduler
  - Full task configuration

#### Cross-Platform Support
- **Windows Compatibility**
  - Full GUI support on Windows
  - Console interface with cmd.exe support
  - Path handling for Windows file system

- **Linux/Mac Support**
  - Full GUI support (with tkinter)
  - Console interface with terminal support
  - Unix path handling

#### Logging
- **Comprehensive Logging**
  - File-based logging
  - Console output
  - Configurable log levels
  - Timestamped entries
  - Error tracking

- **GUI Log Integration**
  - Custom TextHandler for tkinter
  - Thread-safe log updates
  - Auto-scrolling log view

#### Documentation
- **README.md**
  - Complete feature documentation
  - Installation instructions
  - Usage examples
  - Configuration guide
  - Troubleshooting section
  - Security considerations

- **CHANGE_LOG.md**
  - Version history
  - Detailed change tracking
  - Semantic versioning

- **Code Documentation**
  - Comprehensive docstrings
  - Type hints
  - Module documentation
  - Function documentation

#### Development
- **Project Structure**
  - Modular package design
  - Separation of concerns
  - Clean architecture
  - Easy to extend

- **Requirements Management**
  - requirements.txt with version pinning
  - Minimal dependencies
  - Clear dependency purposes

### Technical Details

#### Architecture
- **Modular Design**
  - config_manager.py - Configuration handling
  - winscp_handler.py - SFTP protocol operations
  - scheduler.py - Task scheduling and execution
  - gui.py - GUI interface with tkinter
  - console.py - Console interface
  - main.py - Application entry point

#### Dependencies
- paramiko >= 3.3.1 - SSH/SFTP implementation
- cryptography >= 41.0.5 - Cryptographic operations
- python-dateutil >= 2.8.2 - Date handling
- pytz >= 2023.3 - Timezone support

#### Python Version Support
- Python 3.7+
- Tested on Python 3.8, 3.9, 3.10, 3.11

### Security Features
- Secure password handling
- Key-based authentication support
- Auto-host-key-acceptance with warnings
- Secure configuration file storage
- Connection encryption via SSH/SFTP

### Performance
- Efficient large file handling
- Non-blocking UI operations
- Background task execution
- Threaded file operations
- Progress tracking with minimal overhead

### Known Limitations
- GUI requires tkinter (not included on some Linux distributions)
- Scheduler checks every 10 seconds (configurable in code)
- Task storage limited to JSON file (no database)
- Single connection per instance
- No multi-threading for concurrent transfers

### Future Enhancements (Planned)
- Multiple simultaneous connections
- Drag-and-drop file upload in GUI
- Batch file operations
- File synchronization
- Bandwidth throttling
- Resume failed transfers
- Email notifications for scheduled tasks
- Database backend for task storage
- Web interface
- REST API

---

## Version History Summary

- **[1.0.0]** - 2025-10-19 - Initial release with full feature set

---

## How to Report Issues

Found a bug or have a feature request? Please:
1. Check [existing issues](https://github.com/Pandiyarajk/sftp-pilot/issues) first
2. Create a [new issue](https://github.com/Pandiyarajk/sftp-pilot/issues/new) with detailed information
3. Include version number, OS, and steps to reproduce

---

**Note:** This is the initial release of WinSCP Manager. Future versions will be documented here with detailed change tracking following semantic versioning principles.

---

<div align="center">

Copyright © 2025 [Pandiyaraj Karuppasamy](https://github.com/Pandiyarajk)  
Licensed under the [MIT License](LICENSE)

</div>
