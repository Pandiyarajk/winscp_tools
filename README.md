# SFTP Pilot

> **Disclaimer:** this tool uploads, overwrites and deletes files on remote
> servers, including unattended through its scheduler. It is provided **AS IS**,
> without warranty of any kind, and you use it **entirely at your own risk**: the
> author is not liable for data loss, corruption, downtime or any other damage.
> You are responsible for checking every target, keeping tested backups and being
> authorised to change the servers you connect to. It is not certified for
> regulated or safety-critical use. See [DISCLAIMER.md](https://github.com/Pandiyarajk/sftp-pilot/blob/main/DISCLAIMER.md); the
> [LICENSE](https://github.com/Pandiyarajk/sftp-pilot/blob/main/LICENSE) is the governing text and prevails where the two differ.

A Python SFTP client with a tkinter GUI, a console menu, and a persistent task
scheduler for one-off or recurring uploads, downloads and deletes.

It speaks SFTP directly through [paramiko](https://www.paramiko.org/), so it
runs anywhere Python does. It was called WinSCP Manager (`winscp_tools`) up to
version 1.1.0; see [CHANGE_LOG.md](https://github.com/Pandiyarajk/sftp-pilot/blob/main/CHANGE_LOG.md) for what moved.

**Version:** 2.1.0 · **Python:** 3.11+ · **License:** MIT

## Features

- Upload, download, delete and list over SFTP, with progress for large files
- Password or key authentication (RSA, ECDSA, Ed25519, encrypted keys included)
- Host key verification: new servers are remembered, a changed key is refused
- **Nothing is ever left half-written.** Uploads go to `<name>.part` on the
  server and are renamed into place; downloads go to a local `.part` first.
  A failed or cancelled transfer leaves the previous version untouched.
  paramiko also checks the size of every transfer.
- **Cancel** a running transfer (GUI button, or Ctrl+C in the console)
- **Scheduler:** run once, every N minutes, or daily at a time on chosen
  weekdays. Interval tasks keep their grid, so they do not drift later each run.
- **Retries:** a failed scheduled task is retried with growing delays before it
  counts as failed
- **Unattended:** `sftp-pilot --run-due` runs due tasks from Windows Task
  Scheduler or cron, with nobody logged in to the app; it can share the tasks
  with an open GUI, and a task never runs twice
- **Run history** of every scheduled run, in the GUI, the console and
  `sftp-pilot --history`
- Secrets can come from environment variables instead of the config file

## Quick start

```bash
pip install sftp-pilot
sftp-pilot --init-config     # writes config.ini here; then edit it
sftp-pilot                   # GUI
sftp-pilot --console         # console menu
```

[PyPI](https://pypi.org/project/sftp-pilot/) · `python -m sftp_pilot` works too.

From a source checkout: `pip install .`, or without installing
`pip install -r requirements.txt` then `python main.py`.

Options:

| Option | Meaning |
| --- | --- |
| `--gui` / `--console` | Choose the interface (GUI is the default) |
| `--run-due` | Run the tasks that are due, once, and exit (for Task Scheduler or cron) |
| `--history [N]` | Print the last N scheduled runs (default 20); add `--task ID` for one task |
| `-c`, `--config PATH` | Configuration file (default `config.ini` in the current folder) |
| `--tasks-file PATH` | Where scheduled tasks are saved (default `scheduled_tasks.json` beside the config) |
| `--init-config` | Write a starter config to the `--config` path (never overwrites) |
| `--version` | Print the version |

On Linux the GUI needs tkinter (`sudo apt-get install python3-tk`); the console
interface works without it.

## Configuration

`config.ini` is git-ignored because it holds credentials. Start from
`sftp-pilot --init-config` (the template is
[sftp_pilot/example_config.ini](https://github.com/Pandiyarajk/sftp-pilot/blob/main/sftp_pilot/example_config.ini)):

```ini
[DEFAULT]
protocol = sftp
host = example.com
port = 22
username = your_username
password =
# private_key_path = ~/.ssh/id_ed25519
# private_key_passphrase =
host_key_policy = accept_new
known_hosts_file = known_hosts
timeout = 30
atomic_uploads = true

[PATHS]
remote_upload_dir = /remote/upload/path
local_download_dir = ./downloads

[SCHEDULING]
enabled = true
check_interval = 30
retries = 3
retry_delay = 60

[LOGGING]
log_file = sftp_pilot.log
log_level = INFO
```

| Key | Meaning |
| --- | --- |
| `protocol` | Only `sftp` is supported |
| `password` | Overridden by the `SFTP_PILOT_PASSWORD` environment variable |
| `private_key_path` | Key file; when set, key authentication is used |
| `private_key_passphrase` | Overridden by `SFTP_PILOT_KEY_PASSPHRASE` |
| `host_key_policy` | `accept_new` (default): trust on first connect, refuse a changed key. `reject`: only hosts already known. `auto_add`: no checking, testing only |
| `known_hosts_file` | Where accepted host keys are stored; `~/.ssh/known_hosts` is also read |
| `timeout` | Seconds allowed for connect and authentication |
| `atomic_uploads` | Upload to `<name>.part`, then rename into place. Set `false` only for a server that forbids renames |
| `remote_upload_dir`, `local_download_dir` | Defaults offered by the upload and download prompts |
| `enabled` | `false` stops scheduled tasks from running (app scheduler and `--run-due`) |
| `check_interval` | Seconds between checks for due tasks while the app is open |
| `retries`, `retry_delay` | Extra attempts for a failed scheduled task, and the first delay in seconds; it doubles each time (60, 120, 240) |
| `log_file`, `log_level` | Log file (empty for console only) and level |

Relative paths (`known_hosts_file`, `log_file`, and the default tasks file) are
taken relative to the folder the config file is in, not the current directory.
That is what makes `--run-due` safe to start from Task Scheduler, which starts
programs in `C:\Windows\System32`.

### Keeping the password out of the file

```powershell
$env:SFTP_PILOT_PASSWORD = "..."     # PowerShell
```

```bash
export SFTP_PILOT_PASSWORD='...'     # bash
```

Key authentication is the better option for anything unattended.

### Host keys

The first connection to a server stores its key in `known_hosts_file`. If the
server later presents a different key, the connection is refused with a
warning, since that is what a man-in-the-middle attack looks like. If the key
really did change (server rebuilt), delete that server's line from the file.

## Using it

### GUI

- **Connection:** host, port, user, password or key. Fields start from the
  config file; **Reload Config** reads it again.
- **File Operations:** upload (a remote path ending in `/` keeps the local file
  name), download, delete (asks first). One transfer runs at a time, the window
  stays responsive, and **Cancel** stops it cleanly.
- **Scheduler:** add tasks (once, every N minutes, or daily at a time with
  optional weekdays), start or stop the scheduler, remove the selected tasks.
  The list refreshes every few seconds and shows each task's schedule, next run
  and status (`retrying (1 failed)`, `pending (last run failed)`, ...).
- **History:** every scheduled run, from this window, the console or
  `--run-due`, with its result, attempt, duration and error.
- **Logs:** everything that is written to the log.

Scheduled tasks connect with the settings saved in the config file, not with
whatever is typed in the Connection tab.

### Console

```
1. Connect to server        8. View scheduled tasks
2. Disconnect from server   9. Remove scheduled task
3. Upload file             10. Start scheduler
4. Download file           11. Stop scheduler
5. Delete file             12. Task history
6. List remote files       13. Exit (or q)
7. Schedule task
```

Remove a task by its full ID or an unambiguous prefix of at least four
characters. During a transfer Ctrl+C cancels it; elsewhere it exits cleanly,
stopping the scheduler and disconnecting.

## Running tasks unattended

The scheduler inside the GUI or console only runs while that window is open.
For anything that must happen at night or after a reboot, let the operating
system start `sftp-pilot --run-due` every few minutes. It runs whatever is due
and exits:

| Exit code | Meaning |
| --- | --- |
| 0 | Every due task ran, or nothing was due |
| 1 | At least one task failed (it is retried on a later run if `retries` allows) |
| 2 | The config or the tasks file could not be used |

You can keep the GUI open at the same time. Both use the same tasks file under
a lock, and a task is claimed before it runs, so it never runs twice.

### Windows Task Scheduler

In PowerShell, every 5 minutes, using the `sftp-pilot.exe` that pip installed:

```powershell
$exe     = (Get-Command sftp-pilot).Source
$action  = New-ScheduledTaskAction -Execute $exe -Argument '-c "D:\sftp\config.ini" --run-due'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "SFTP Pilot run-due" -Action $action -Trigger $trigger
```

This runs while you are logged on. To run when nobody is logged on, register it
from an **elevated** PowerShell with
`-Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U)`;
a normal (non-admin) PowerShell is refused with "Access is denied". Check the
outcome with `Get-ScheduledTaskInfo "SFTP Pilot run-due"` (`LastTaskResult` is
the exit code above), and remove it with
`Unregister-ScheduledTask "SFTP Pilot run-due"`.

### cron (Linux, macOS)

`crontab -e`, then one line (every 5 minutes; use the full path from
`which sftp-pilot`):

```
*/5 * * * * /home/me/.venv/bin/sftp-pilot -c /home/me/sftp/config.ini --run-due
```

### Scheduling notes

- Retries happen on later checks, so with `--run-due` every 5 minutes a 60 s
  retry delay waits for the next run.
- Interval tasks run on a fixed grid from their first run (09:00, 09:15, ...).
  After downtime the missed slots are skipped, not replayed.
- A task that was running when its process died is picked up again and marked
  as interrupted. A task claimed by a live process is never taken over.
- Scheduled deletes run unattended, on every run of a recurring task. Check the
  path twice.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The integration tests start a throwaway SFTP server (asyncssh) on localhost, so
they need no external server. They cover transfers, cancel, atomic replace,
key authentication, host key changes, `--run-due` started from an unrelated
folder, and two processes racing for the same tasks.

```
sftp_pilot/
  cli.py             command-line entry point (sftp-pilot), --run-due, --history
  config_manager.py  config.ini reading, environment overrides, path resolution
  sftp_handler.py    SFTP connection and file operations
  scheduler.py       task model, schedules, retries, file lock, claims, history
  runner.py          runs a task on its own connection
  gui.py             tkinter interface
  console.py         console menu
tests/               pytest suite
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Host key ... does not match` | The server key changed. Confirm why before removing its line from `known_hosts` |
| `not a known host and host_key_policy is 'reject'` | Add the key to `known_hosts`, or use `accept_new` |
| Authentication failed | Credentials, key path and passphrase; the server's allowed auth methods |
| Scheduled task never runs | `enabled = true`, and either the app's scheduler is started or `--run-due` is registered |
| `--run-due` exits 2 | Run the same command in a terminal to see the message; usually the `-c` path |
| Upload fails at the rename step | The server forbids renames: set `atomic_uploads = false` |
| GUI does not start | `python -m tkinter`; on Linux install `python3-tk`; or use `--console` |

## License

MIT, see [LICENSE](https://github.com/Pandiyarajk/sftp-pilot/blob/main/LICENSE). Change history is in [CHANGE_LOG.md](https://github.com/Pandiyarajk/sftp-pilot/blob/main/CHANGE_LOG.md).
