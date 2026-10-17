#!/usr/bin/env python3
"""
WinSCP Manager - source checkout entry point.

Kept so `python main.py` still works from a clone; the real entry point is
winscp_manager.cli (installed as the `winscp-manager` command).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-17-2026
"""

import sys

from winscp_manager.cli import main

if __name__ == '__main__':
    sys.exit(main())
