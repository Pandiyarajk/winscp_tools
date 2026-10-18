"""
Console Interface for SFTP Pilot

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import logging
import signal
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator, Optional

from .config_manager import ConfigManager
from .runner import make_task_executor
from .scheduler import ScheduledTask, TaskScheduler, TaskType
from .sftp_handler import CANCELLED, SFTPHandler


def _progress_printer(verb: str):
    def callback(done: int, total: int) -> None:
        percent = (done / total * 100) if total else 100.0
        print(f"\r{verb}: {percent:5.1f}% ({done}/{total} bytes)  Ctrl+C cancels", end='', flush=True)
    return callback


@contextmanager
def _ctrl_c_cancels() -> Iterator[threading.Event]:
    """
    During a transfer, Ctrl+C sets an event the transfer checks between
    chunks, instead of raising KeyboardInterrupt somewhere inside paramiko
    (which could leave the SFTP channel mid-request).
    """
    cancel = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        yield cancel
    finally:
        signal.signal(signal.SIGINT, previous)


def _report(ok: bool, handler: SFTPHandler, what: str) -> None:
    if ok:
        print(f"\nOK: {what} completed")
    elif handler.last_error == CANCELLED:
        print(f"\nCancelled: {what} stopped, nothing was left half-written")
    else:
        print(f"\nFAILED: {what} failed: {handler.last_error}")


def _ask_int(prompt: str, default: int, minimum: int = 0) -> Optional[int]:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"FAILED: '{raw}' is not a whole number")
        return None
    if value < minimum:
        print(f"FAILED: must be at least {minimum}")
        return None
    return value


class ConsoleInterface:
    """Console-based interface for SFTP Pilot"""

    def __init__(self, config_path: str = "config.ini", tasks_file: str = "scheduled_tasks.json"):
        """
        Initialize console interface

        Args:
            config_path: Configuration file to read
            tasks_file: Where scheduled tasks are stored
        """
        self.config_path = config_path
        self.tasks_file = tasks_file
        self.config_manager: Optional[ConfigManager] = None
        self.sftp_handler: Optional[SFTPHandler] = None
        self.scheduler = TaskScheduler(tasks_file, runner="console")
        self.running = True
        self.logger = logging.getLogger(__name__)

    @property
    def connected(self) -> bool:
        """True while the interactive connection is alive"""
        return bool(self.sftp_handler and self.sftp_handler.is_connected())

    def run(self):
        """Run the console interface"""
        print("=" * 60)
        print("SFTP Pilot - Console Interface")
        print("=" * 60)

        try:
            self.config_manager = ConfigManager(self.config_path)
            self.logger.info("Configuration loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            print(f"Warning: Could not load configuration file {self.config_path}")

        if self.config_manager:
            sched_cfg = self.config_manager.get_scheduling_config()
            self.scheduler.check_interval = sched_cfg['check_interval']
            self.scheduler.retries = sched_cfg['retries']
            self.scheduler.retry_delay = sched_cfg['retry_delay']
            self.scheduler.set_task_executor(
                make_task_executor(self.config_manager.get_connection_details)
            )

        try:
            while self.running:
                self.show_menu()
                choice = input("\nEnter your choice: ").strip()
                self.handle_choice(choice)
        except (KeyboardInterrupt, EOFError):
            print()
            self.exit_app()

    def show_menu(self):
        """Display main menu"""
        state = "connected" if self.connected else "not connected"
        sched = "running" if self.scheduler.running else "stopped"
        print("\n" + "=" * 60)
        print(f"Main Menu   (server: {state}, scheduler: {sched})")
        print("=" * 60)
        print("1. Connect to server")
        print("2. Disconnect from server")
        print("3. Upload file")
        print("4. Download file")
        print("5. Delete file")
        print("6. List remote files")
        print("7. Schedule task")
        print("8. View scheduled tasks")
        print("9. Remove scheduled task")
        print("10. Start scheduler")
        print("11. Stop scheduler")
        print("12. Exit")
        print("=" * 60)

    def handle_choice(self, choice: str):
        """Handle menu choice"""
        actions = {
            '1': self.connect,
            '2': self.disconnect,
            '3': self.upload_file,
            '4': self.download_file,
            '5': self.delete_file,
            '6': self.list_files,
            '7': self.schedule_task,
            '8': self.view_tasks,
            '9': self.remove_task,
            '10': self.start_scheduler,
            '11': self.stop_scheduler,
            '12': self.exit_app
        }

        action = actions.get(choice)
        if not action:
            print("\nInvalid choice. Please try again.")
            return
        try:
            action()
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as e:
            self.logger.error(f"Error: {e}")
            print(f"\nError: {e}")

    def _require_connection(self) -> Optional[SFTPHandler]:
        if self.sftp_handler and self.sftp_handler.is_connected():
            return self.sftp_handler
        if self.sftp_handler:
            print("\nFAILED: the connection was lost. Please connect again.")
        else:
            print("\nFAILED: not connected to server. Please connect first.")
        return None

    def connect(self):
        """Connect to server"""
        if self.connected:
            print("\nAlready connected to server")
            return

        if not self.config_manager:
            print("\nConfiguration not loaded. Cannot connect.")
            return

        conn_details = self.config_manager.get_connection_details()
        print(f"\nConnecting to {conn_details['host']}:{conn_details['port']}...")

        self.sftp_handler = SFTPHandler.from_config(conn_details)
        if self.sftp_handler.connect():
            print("OK: connected")
        else:
            print(f"FAILED: {self.sftp_handler.last_error}")

    def disconnect(self):
        """Disconnect from server"""
        if not self.sftp_handler:
            print("\nNot connected to server")
            return

        self.sftp_handler.disconnect()
        self.sftp_handler = None
        print("\nOK: disconnected")

    def upload_file(self):
        """Upload file to server"""
        handler = self._require_connection()
        if not handler:
            return

        local_path = input("\nEnter local file path: ").strip().strip('"')
        default_dir = self.config_manager.get_paths()['remote_upload_dir'] if self.config_manager else ''
        remote_path = input(f"Enter remote destination path (end with / for a folder) [{default_dir}]: ").strip()
        remote_path = remote_path or default_dir

        if not local_path or not remote_path:
            print("FAILED: both paths are required")
            return
        if not remote_path.endswith('/') and remote_path == default_dir:
            remote_path += '/'

        print(f"\nUploading {local_path} to {remote_path}...")
        with _ctrl_c_cancels() as cancel:
            ok = handler.upload_file(local_path, remote_path, _progress_printer("Uploading"), cancel)
        _report(ok, handler, "upload")

    def download_file(self):
        """Download file from server"""
        handler = self._require_connection()
        if not handler:
            return

        remote_path = input("\nEnter remote file path: ").strip()
        default_dir = self.config_manager.get_paths()['local_download_dir'] if self.config_manager else ''
        local_path = input(f"Enter local destination (file or folder) [{default_dir}]: ").strip().strip('"')
        local_path = local_path or default_dir

        if not remote_path or not local_path:
            print("FAILED: both paths are required")
            return

        print(f"\nDownloading {remote_path} to {local_path}...")
        with _ctrl_c_cancels() as cancel:
            ok = handler.download_file(remote_path, local_path, _progress_printer("Downloading"), cancel)
        _report(ok, handler, "download")

    def delete_file(self):
        """Delete file from server"""
        handler = self._require_connection()
        if not handler:
            return

        remote_path = input("\nEnter remote file path to delete: ").strip()

        if not remote_path:
            print("FAILED: path is required")
            return

        confirm = input(f"Permanently delete {remote_path} on the server? Type 'yes' to confirm: ").strip().lower()
        if confirm != 'yes':
            print("Cancelled")
            return

        if handler.delete_file(remote_path):
            print("OK: file deleted")
        else:
            print("FAILED: delete failed (see log)")

    def list_files(self):
        """List files in remote directory"""
        handler = self._require_connection()
        if not handler:
            return

        remote_path = input("\nEnter remote directory path [/]: ").strip() or "/"
        files = handler.list_files(remote_path)

        if files:
            print(f"\nFiles in {remote_path}:")
            print("-" * 60)
            for name in files:
                print(f"  {name}")
            print("-" * 60)
        else:
            print("\nNo files found or error occurred")

    def schedule_task(self):
        """Schedule a new task"""
        print("\nSchedule New Task")
        print("-" * 60)
        print("Task Types: 1) Upload  2) Download  3) Delete")
        task_choice = input("Select task type (1-3): ").strip()

        task_type = {'1': TaskType.UPLOAD, '2': TaskType.DOWNLOAD, '3': TaskType.DELETE}.get(task_choice)
        if not task_type:
            print("FAILED: invalid task type")
            return

        label = "remote file to delete" if task_type == TaskType.DELETE else "source path"
        source_path = input(f"Enter {label}: ").strip().strip('"')
        dest_path = ""
        if task_type in (TaskType.UPLOAD, TaskType.DOWNLOAD):
            dest_path = input("Enter destination path: ").strip().strip('"')

        delay_minutes = _ask_int("Run in how many minutes?", 5)
        if delay_minutes is None:
            return

        recurring = input("Recurring task? (yes/no) [no]: ").strip().lower() == 'yes'
        interval_minutes = 0
        if recurring:
            interval_minutes = _ask_int("Interval in minutes", 60, minimum=1)
            if interval_minutes is None:
                return

        task_id = str(uuid.uuid4())
        scheduled_time = datetime.now() + timedelta(minutes=delay_minutes)
        try:
            task = ScheduledTask(task_id, task_type, source_path, dest_path,
                                 scheduled_time, recurring, interval_minutes)
        except ValueError as e:
            print(f"FAILED: {e}")
            return

        self.scheduler.add_task(task)
        print(f"\nOK: task scheduled (ID: {task_id[:8]})")
        print(f"  Will run at: {scheduled_time:%Y-%m-%d %H:%M:%S}")
        if not self.scheduler.running:
            print("  The scheduler is stopped: start it (option 10) for the task to run.")

    def view_tasks(self):
        """View all scheduled tasks"""
        tasks = self.scheduler.get_all_tasks()

        if not tasks:
            print("\nNo scheduled tasks")
            return

        print("\nScheduled Tasks")
        print("=" * 80)

        for task in tasks:
            print(f"\nTask ID: {task.task_id}")
            print(f"Type: {task.task_type.value}")
            print(f"Source: {task.source_path}")
            print(f"Destination: {task.dest_path or 'N/A'}")
            print(f"Next Run: {task.next_run:%Y-%m-%d %H:%M:%S}" if task.next_run else "Next Run: N/A")
            print(f"Status: {task.describe_status()}")
            if task.error_message:
                print(f"Last error: {task.error_message}")
            print(f"Recurring: {'every %d minutes' % task.interval_minutes if task.recurring else 'No'}")
            print("-" * 80)

    def remove_task(self):
        """Remove a scheduled task"""
        task_id = input("\nEnter task ID to remove (at least the first 4 characters): ").strip()
        task = self.scheduler.find_task(task_id)
        if not task:
            print("FAILED: no single task matches that ID")
            return
        if self.scheduler.remove_task(task.task_id):
            print(f"OK: task {task.task_id[:8]} removed")
        else:
            print("FAILED: could not remove task")

    def start_scheduler(self):
        """Start the scheduler"""
        if self.scheduler.running:
            print("\nScheduler is already running")
            return
        if not self.config_manager:
            print("\nFAILED: the scheduler needs a loaded configuration to connect")
            return
        if not self.config_manager.get_scheduling_config()['enabled']:
            print("\nFAILED: scheduling is disabled ([SCHEDULING] enabled = false)")
            return

        self.scheduler.start()
        print("\nOK: scheduler started")

    def stop_scheduler(self):
        """Stop the scheduler"""
        if not self.scheduler.running:
            print("\nScheduler is not running")
            return

        self.scheduler.stop()
        print("\nOK: scheduler stopped")

    def exit_app(self):
        """Exit the application"""
        print("\nExiting...")

        if self.scheduler.running:
            self.scheduler.stop()

        if self.sftp_handler:
            self.sftp_handler.disconnect()

        self.running = False
        print("Goodbye!")


def run_console(config_path: str = "config.ini", tasks_file: str = "scheduled_tasks.json"):
    """
    Run the console interface

    Args:
        config_path: Configuration file to read
        tasks_file: Where scheduled tasks are stored
    """
    ConsoleInterface(config_path, tasks_file).run()
