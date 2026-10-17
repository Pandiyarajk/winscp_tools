"""
WinSCP Manager command-line entry point (installed as `winscp-manager`).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-17-2026
"""

import argparse
import logging
import os
import sys
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


def main(argv: Optional[List[str]] = None) -> int:
    """
    Parse arguments and start the chosen interface

    Args:
        argv: Argument list (defaults to sys.argv[1:])

    Returns:
        Process exit code
    """
    parser = argparse.ArgumentParser(
        prog='winscp-manager',
        description='WinSCP Manager - SFTP file transfer and scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  winscp-manager                      # GUI (default)
  winscp-manager --console            # console menu
  winscp-manager -c D:\\cfg\\prod.ini   # use another config file

{WARNING}"""
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--gui', action='store_true', help='Run GUI interface (default)')
    group.add_argument('--console', action='store_true', help='Run console interface')
    parser.add_argument('-c', '--config', default='config.ini',
                        help='Configuration file (default: config.ini in the current directory)')
    parser.add_argument('--tasks-file', default='scheduled_tasks.json',
                        help='Where scheduled tasks are stored (default: scheduled_tasks.json)')
    parser.add_argument('--version', action='version', version=f'WinSCP Manager {__version__}')

    args = parser.parse_args(argv)
    setup_logging(args.config)

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
