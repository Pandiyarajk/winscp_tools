# SFTP Pilot

> **Disclaimer:** this tool uploads, overwrites and deletes files on remote
> servers, including unattended through its scheduler. It is provided **AS IS**,
> without warranty of any kind, and you use it **entirely at your own risk**: the
> author is not liable for data loss, corruption, downtime or any other damage.
> You are responsible for checking every target, keeping tested backups and being
> authorised to change the servers you connect to. It is not certified for
> regulated or safety-critical use. See [DISCLAIMER.md](DISCLAIMER.md); the
> [LICENSE](LICENSE) is the governing text and prevails where the two differ.

A Python SFTP client with a tkinter GUI, a console menu, and a persistent task
scheduler for one-off or recurring uploads, downloads and deletes.

It speaks SFTP directly through [paramiko](https://www.paramiko.org/), so it
runs anywhere Python does. It was called WinSCP Manager (`winscp_tools`) up to
version 1.1.0; see [CHANGE_LOG.md](CHANGE_LOG.md) for what moved.

**Version:** 2.0.1 · **Python:** 3.11+ · **License:** MIT

## Features

- Upload, download, delete and list over SFTP, with progress for large files
- Password or key authentication (RSA, ECDSA, Ed25519, encrypted keys included)
- Host key verification: new servers are remembered, a changed key is refused
- Remote folders are created on upload; downloads land under a temporary
  `.part` name, so a failed transfer never leaves a truncated file behind
- Scheduler with one-off and recurring tasks, saved to disk between sessions;
  each run opens its own connection, so a dropped interactive session does not
  stop scheduled work
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
| `-c`, `--config PATH` | Configuration file (default `config.ini` in the current folder) |
| `--tasks-file PATH` | Where scheduled tasks are saved (default `scheduled_tasks.json`) |
| `--init-config` | Write a starter config to the `--config` path (never overwrites) |
| `--version` | Print the version |

On Linux the GUI needs tkinter (`sudo apt-get install python3-tk`); the console
interface works without it.

## Configuration

`config.ini` is git-ignored because it holds credentials. Start from
`sftp-pilot --init-config` (the template is
[sftp_pilot/example_config.ini](sftp_pilot/example_config.ini)):

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

[PATHS]
remote_upload_dir = /remote/upload/path
local_download_dir = ./downloads

[SCHEDULING]
enabled = true
check_interval = 30

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
| `remote_upload_dir`, `local_download_dir` | Defaults offered by the upload and download prompts |
| `enabled` | `false` stops the scheduler from being started |
| `check_interval` | Seconds between checks for due tasks |
| `log_file`, `log_level` | Log file (empty for console only) and level |

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
  name), download, delete (asks first). One transfer runs at a time and the
  window stays responsive.
- **Scheduler:** add tasks, start or stop the scheduler, remove the selected
  tasks. The list refreshes every few seconds. A recurring task whose last run
  failed shows `pending (last run failed)` and keeps its schedule.
- **Logs:** everything that is written to the log.

Scheduled tasks connect with the settings saved in the config file, not with
whatever is typed in the Connection tab.

### Console

```
1. Connect to server        7. Schedule task
2. Disconnect from server   8. View scheduled tasks
3. Upload file              9. Remove scheduled task
4. Download file           10. Start scheduler
5. Delete file             11. Stop scheduler
6. List remote files       12. Exit
```

Remove a task by its full ID or an unambiguous prefix of at least four
characters. Ctrl+C exits cleanly, stopping the scheduler and disconnecting.

### Scheduling notes

- The scheduler only runs while the application is open. For jobs that must
  run with nobody logged in, use the operating system's scheduler (Task
  Scheduler, cron) instead.
- A task that was running when the application closed is run again at the next
  start, and is marked as interrupted.
- Scheduled deletes run unattended and every interval for recurring tasks.
  Check the path twice.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The integration tests start a throwaway SFTP server (asyncssh) on localhost, so
they need no external server. They cover transfers, key authentication, host
key changes and a scheduled run end to end.

```
sftp_pilot/
  cli.py             command-line entry point (sftp-pilot)
  config_manager.py  config.ini reading, environment overrides
  sftp_handler.py  SFTP connection and file operations
  scheduler.py       task model, persistence, scheduler thread
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
| Scheduled task never runs | The scheduler is started, `enabled = true`, and the app is still open |
| GUI does not start | `python -m tkinter`; on Linux install `python3-tk`; or use `--console` |

## License

MIT, see [LICENSE](LICENSE). Change history is in [CHANGE_LOG.md](CHANGE_LOG.md).
