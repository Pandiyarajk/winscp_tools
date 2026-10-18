"""
SFTP Pilot command-line entry point (installed as `sftp-pilot`).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import argparse
import getpass
import logging
import os
import sys
from importlib import resources
from typing import List, Optional

from . import __version__

WARNING = """\
WARNING: this tool uploads, overwrites and deletes files on remote servers,
including unattended through the scheduler. It is provided AS IS, without
warranty of any kind, and you use it entirely at your own risk. Check every
target path, keep tested backups, and only act on servers you are authorised
to change. See DISCLAIMER.md; LICENSE is the governing text.
"""


def setup_logging(config_path: str) -> None:
    """
    Configure root logging from the [LOGGING] section, falling back to INFO
    on the console when the configuration cannot be read.

    Args:
        config_path: Path to the configuration file
    """
    level_name, log_file = "INFO", ""
    if os.path.exists(config_path):
        try:
            from .config_manager import ConfigManager
            cfg = ConfigManager(config_path).get_logging_config()
            level_name, log_file = cfg['log_level'], cfg['log_file']
        except Exception as e:
            print(f"Warning: could not read logging settings: {e}", file=sys.stderr)

    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=handlers,
        force=True,
    )
    # paramiko is chatty at INFO; keep its noise out unless DEBUG was asked for.
    if level_name != "DEBUG":
        logging.getLogger("paramiko").setLevel(logging.WARNING)


def init_config(config_path: str) -> int:
    """
    Write the bundled example configuration to config_path

    Args:
        config_path: Where to write it; an existing file is left untouched

    Returns:
        Process exit code (1 when the file already exists)
    """
    if os.path.exists(config_path):
        print(f"{config_path} already exists; not overwriting it.", file=sys.stderr)
        return 1
    template = resources.files(__package__).joinpath('example_config.ini').read_text(encoding='utf-8')
    with open(config_path, 'x', encoding='utf-8') as f:
        f.write(template)
    print(f"Wrote {os.path.abspath(config_path)}: fill in host, username and authentication.")
    return 0


def manage_secrets(config_path: str, server: str, store_password: bool, store_passphrase: bool,
                   forget: bool) -> int:
    """
    Store or remove a server's password or key passphrase in the OS keyring

    Args:
        config_path: Configuration file
        server: Server name ('' for the default server)
        store_password: Prompt for a password and store it
        store_passphrase: Prompt for a key passphrase and store it
        forget: Remove both stored secrets of the server

    Returns:
        0 on success, 1 when nothing was stored (empty or mismatched input),
        2 when the config or the keyring could not be used
    """
    from . import keystore
    from .config_manager import ConfigManager

    try:
        who = ConfigManager(config_path).identity(server)
    except Exception as e:
        print(f"Cannot use configuration {os.path.abspath(config_path)}: {e}", file=sys.stderr)
        return 2
    target = f"{who['username']}@{who['host']}:{who['port']}"
    try:
        keystore.ensure_available()  # before asking anyone to type a secret
        if forget:
            removed = [kind for kind in keystore.KINDS
                       if keystore.delete_secret(kind, who['username'], who['host'], who['port'])]
            print(f"Removed from the keyring for {target}: {', '.join(removed) or 'nothing was stored'}")
            return 0
        kind = "password" if store_password else "passphrase"
        secret = getpass.getpass(f"{kind.capitalize()} for {target} (not shown): ")
        if not secret:
            print("Nothing entered; nothing stored.", file=sys.stderr)
            return 1
        if getpass.getpass("Again: ") != secret:
            print("The two entries differ; nothing stored.", file=sys.stderr)
            return 1
        keystore.set_secret(kind, who['username'], who['host'], who['port'], secret)
    except keystore.KeyringUnavailable as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"Stored the {kind} for {target} in the keyring.")
    print(f"Make the server use it by adding to [{who['section']}] in {config_path}:")
    print("    password_store = keyring")
    print("and remove the plain-text value from the file. The keyring entry wins over the file; "
          "an environment variable wins over both.")
    return 0


def run_due(config_path: str, tasks_file: str) -> int:
    """
    Run every due task once, for an external scheduler

    Args:
        config_path: Configuration file
        tasks_file: Tasks file shared with the GUI and console

    Returns:
        0 when every task ran (or none was due), 1 when a task failed,
        2 when the configuration or the tasks file could not be used
    """
    from .config_manager import ConfigManager
    from .runner import make_task_executor
    from .scheduler import TaskScheduler

    log = logging.getLogger("sftp_pilot.run_due")
    try:
        cfg = ConfigManager(config_path)
        names = cfg.server_names()
        if not names:
            raise ValueError("the config describes no server (add host and username to [DEFAULT])")
        for name in names:  # validate every server before touching any task
            cfg.get_connection_details(name)
        sched_cfg = cfg.get_scheduling_config()
    except Exception as e:
        log.error(f"Cannot use configuration {os.path.abspath(config_path)}: {e}")
        return 2
    if not sched_cfg['enabled']:
        log.info("Scheduling is disabled ([SCHEDULING] enabled = false); nothing run")
        return 0

    scheduler = TaskScheduler(tasks_file, retries=sched_cfg['retries'],
                              retry_delay=sched_cfg['retry_delay'], runner="run-due")
    scheduler.set_task_executor(make_task_executor(cfg.get_connection_details))
    try:
        records = scheduler.run_due_tasks()
    except (TimeoutError, RuntimeError) as e:
        log.error(f"Cannot use tasks file {tasks_file}: {e}")
        return 2

    failed = [r for r in records if r['result'] != 'ok']
    log.info(f"run-due: {len(records)} task(s) run, {len(failed)} failed")
    return 1 if failed else 0


def show_history(tasks_file: str, limit: int, task_id: str = "") -> int:
    """
    Print recent task runs, newest first

    Args:
        tasks_file: Tasks file whose history to read
        limit: Number of runs to print
        task_id: Only this task (ID or prefix)

    Returns:
        Process exit code
    """
    from .scheduler import TaskScheduler

    records = TaskScheduler(tasks_file).read_history(task_id, max(1, limit))
    if not records:
        print("No task runs recorded yet.")
        return 0
    for r in records:
        line = (f"{r.get('time', '?')}  {str(r.get('task_id', ''))[:8]}  {r.get('server', ''):8}  "
                f"{r.get('type', ''):8}  "
                f"{r.get('result', ''):6}  try {r.get('attempt', 1)}  {r.get('duration_s', 0):>8}s  "
                f"{r.get('runner', '')}")
        if r.get('error'):
            line += f"  {r['error']}"
        print(line)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """
    Parse arguments and start the chosen interface

    Args:
        argv: Argument list (defaults to sys.argv[1:])

    Returns:
        Process exit code
    """
    parser = argparse.ArgumentParser(
        prog='sftp-pilot',
        description='SFTP Pilot - SFTP file transfer and scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  sftp-pilot                      # GUI (default)
  sftp-pilot --console            # console menu
  sftp-pilot --init-config          # write a starter config.ini
  sftp-pilot -c D:\\cfg\\prod.ini   # use another config file
  sftp-pilot -c D:\\cfg\\prod.ini --run-due    # from Task Scheduler / cron
  sftp-pilot --history 50           # recent task runs
  sftp-pilot --store-password --server backup   # keep its password in the OS keyring

{WARNING}"""
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--gui', action='store_true', help='Run GUI interface (default)')
    group.add_argument('--console', action='store_true', help='Run console interface')
    group.add_argument('--init-config', action='store_true',
                       help='Write a starter configuration to --config (never overwrites) and exit')
    group.add_argument('--run-due', action='store_true',
                       help='Run the tasks that are due, once, then exit (for Task Scheduler or cron). '
                            'Exit code 0: all ran or none due; 1: a task failed; 2: config or lock error')
    group.add_argument('--history', nargs='?', type=int, const=20, metavar='N',
                       help='Print the last N task runs (default 20) and exit')
    group.add_argument('--store-password', action='store_true',
                       help='Store a server password in the OS keyring (prompted, not echoed) and exit; '
                            'needs sftp-pilot[keyring]')
    group.add_argument('--store-passphrase', action='store_true',
                       help='Store a server key passphrase in the OS keyring and exit')
    group.add_argument('--forget-secrets', action='store_true',
                       help="Remove a server's password and passphrase from the OS keyring and exit")
    parser.add_argument('--server', default='', metavar='NAME',
                        help='With the keyring options: which server (default: the [DEFAULT] server)')
    parser.add_argument('--task', default='', metavar='ID',
                        help='With --history: only this task (ID or its first characters)')
    parser.add_argument('-c', '--config', default='config.ini',
                        help='Configuration file (default: config.ini in the current directory)')
    parser.add_argument('--tasks-file', default=None,
                        help='Where scheduled tasks are stored (default: scheduled_tasks.json '
                             'next to the configuration file)')
    parser.add_argument('--version', action='version', version=f'SFTP Pilot {__version__}')

    args = parser.parse_args(argv)
    if args.init_config:
        return init_config(args.config)
    if args.store_password or args.store_passphrase or args.forget_secrets:
        return manage_secrets(args.config, args.server, args.store_password, args.store_passphrase,
                              args.forget_secrets)
    if args.tasks_file is None:
        # Beside the config, not the working directory: Task Scheduler starts
        # programs in System32 and cron in the home folder.
        args.tasks_file = os.path.join(os.path.dirname(os.path.abspath(args.config)),
                                       'scheduled_tasks.json')
    if args.history is not None:
        return show_history(args.tasks_file, args.history, args.task)
    setup_logging(args.config)
    if args.run_due:
        return run_due(args.config, args.tasks_file)

    if args.console:
        from .console import run_console
        run_console(args.config, args.tasks_file)
        return 0

    try:
        from .gui import run_gui
    except ImportError as e:
        print(f"Error: Failed to load GUI. {e}", file=sys.stderr)
        print("Try running with --console for console interface", file=sys.stderr)
        return 1
    run_gui(args.config, args.tasks_file)
    return 0


if __name__ == '__main__':
    sys.exit(main())
