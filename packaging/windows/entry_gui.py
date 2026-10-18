"""
Entry point of sftp-pilot-gui.exe (windowed build, no console window).

There is no console, so sys.stdout and sys.stderr are None; the application
only logs and shows dialogs, so nothing writes to them. Errors that would
otherwise vanish are shown in a message box.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import sys
import traceback


# Anything that picks a mode. With none of these the window opens, which is what
# the Start menu shortcut runs; `--run-due` from Task Scheduler runs without a window.
MODE_FLAGS = {"--gui", "--console", "--init-config", "--run-due", "--history", "--store-password",
              "--store-passphrase", "--forget-secrets", "--version", "-h", "--help"}


def run() -> int:
    from sftp_pilot.cli import main
    args = sys.argv[1:]
    if not MODE_FLAGS.intersection(args):
        args = ["--gui", *args]
    return main(args)


if __name__ == "__main__":
    try:
        code = run()
    except SystemExit as e:  # argparse errors and --version end up here
        code = e.code if isinstance(e.code, int) else 1
    except Exception:
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("SFTP Pilot could not start", traceback.format_exc()[-1500:])
        except Exception:
            pass
        code = 1
    sys.exit(code)
