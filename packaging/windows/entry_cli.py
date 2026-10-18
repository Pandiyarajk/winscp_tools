"""
Entry point of sftp-pilot.exe (console build): the command-line tool, the
console menu, --run-due for Task Scheduler, --history and the keyring commands.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import sys

from sftp_pilot.cli import main

if __name__ == "__main__":
    sys.exit(main())
