"""
SFTP Pilot command-line entry point (installed as `sftp-pilot`).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import argparse
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

{WARNING}"""
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--gui', action='store_true', help='Run GUI interface (default)')
    group.add_argument('--console', action='store_true', help='Run console interface')
    group.add_argument('--init-config', action='store_true',
                       help='Write a starter configuration to --config (never overwrites) and exit')
    parser.add_argument('-c', '--config', default='config.ini',
                        help='Configuration file (default: config.ini in the current directory)')
    parser.add_argument('--tasks-file', default='scheduled_tasks.json',
                        help='Where scheduled tasks are stored (default: scheduled_tasks.json)')
    parser.add_argument('--version', action='version', version=f'SFTP Pilot {__version__}')

    args = parser.parse_args(argv)
    if args.init_config:
        return init_config(args.config)
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
