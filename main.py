#!/usr/bin/env python3
"""
SFTP Pilot - source checkout entry point.

Kept so `python main.py` still works from a clone; the real entry point is
sftp_pilot.cli (installed as the `sftp-pilot` command).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import sys

from sftp_pilot.cli import main

if __name__ == '__main__':
    sys.exit(main())
