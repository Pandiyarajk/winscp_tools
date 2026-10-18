"""
Task Scheduler for automated file operations.

The tasks file is the source of truth and may be shared by several processes
(the GUI's scheduler thread and `sftp-pilot --run-due` started by Task
Scheduler or cron). Every change is a read-modify-write under an inter-process
file lock, and a task is claimed (marked running with this process's identity)
before it runs, so two processes never run the same task.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, time as dtime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional

HISTORY_MAX_BYTES = 5 * 1024 * 1024
FOREIGN_CLAIM_TIMEOUT = timedelta(hours=24)
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class TaskType(Enum):
    """Types of scheduled tasks"""
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE = "delete"


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def parse_daily_time(value: str) -> dtime:
    """
    Parse "HH:MM" (24 hour)

    Args:
        value: Time of day

    Returns:
        The parsed time

    Raises:
        ValueError: If it is not a valid HH:MM
    """
    try:
        hours, minutes = value.strip().split(":")
        return dtime(int(hours), int(minutes))
    except (ValueError, AttributeError):
        raise ValueError(f"Time of day must be HH:MM (24 hour), got '{value}'") from None


class ScheduledTask:
    """Represents a scheduled task"""

    def __init__(self, task_id: str, task_type: TaskType,
                 source_path: str, dest_path: str = "",
                 scheduled_time: Optional[datetime] = None,
                 recurring: bool = False, interval_minutes: int = 0,
                 daily_time: str = "", weekdays: Optional[List[int]] = None,
                 server: str = ""):
        """
        Initialize a scheduled task

        Args:
            task_id: Unique task identifier
            task_type: Type of task (upload, download, delete)
            source_path: Source file path
            dest_path: Destination path (for upload/download)
            scheduled_time: First run for one-off and interval tasks; interval
                runs fall on this time plus whole intervals, so they never drift
            recurring: Whether task should repeat
            interval_minutes: Interval for recurring tasks
            daily_time: "HH:MM" to run every day at that time (implies recurring)
            weekdays: Days a daily task runs, 0 = Monday; empty means every day
            server: Name of the configured server it runs against ('' = the default server)

        Raises:
            ValueError: If the task definition is incomplete
        """
        if not source_path:
            raise ValueError("Source path is required")
        if task_type in (TaskType.UPLOAD, TaskType.DOWNLOAD) and not dest_path:
            raise ValueError(f"Destination path is required for {task_type.value} tasks")
        weekdays = sorted(set(weekdays or []))
        if any(d not in range(7) for d in weekdays):
            raise ValueError("Weekdays must be 0 (Monday) to 6 (Sunday)")
        if daily_time:
            parse_daily_time(daily_time)
            recurring = True
            interval_minutes = 0
        elif weekdays:
            raise ValueError("Weekdays only apply to a daily time")
        if recurring and not daily_time and interval_minutes <= 0:
            raise ValueError("Recurring tasks need an interval of at least 1 minute")

        self.task_id = task_id
        self.task_type = task_type
        self.source_path = source_path
        self.dest_path = dest_path
        self.scheduled_time = scheduled_time or datetime.now()
        self.recurring = recurring
        self.interval_minutes = interval_minutes if recurring else 0
        self.daily_time = daily_time.strip()
        self.weekdays = weekdays
        self.server = server.strip()
        self.status = TaskStatus.PENDING
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = (
            self.following_run(datetime.now()) if self.daily_time else self.scheduled_time
        )
        self.error_message = ""
        self.attempt = 0
        self.claim: Optional[Dict[str, Any]] = None

    def following_run(self, after: datetime) -> Optional[datetime]:
        """
        The first scheduled run strictly after `after`

        Args:
            after: Reference time

        Returns:
            The next run, or None for a one-off task
        """
        if self.daily_time:
            at = parse_daily_time(self.daily_time)
            for offset in range(8):
                candidate = datetime.combine(after.date() + timedelta(days=offset), at)
                if candidate > after and (not self.weekdays or candidate.weekday() in self.weekdays):
                    return candidate
            return None
        if self.recurring and self.interval_minutes > 0:
            step = timedelta(minutes=self.interval_minutes)
            if after < self.scheduled_time:
                return self.scheduled_time
            slots = (after - self.scheduled_time) // step + 1
            return self.scheduled_time + slots * step
        return None

    @property
    def server_label(self) -> str:
        """Server name for display"""
        return self.server or "default"

    def describe_schedule(self) -> str:
        """Human readable schedule"""
        if self.daily_time:
            if not self.weekdays:
                return f"daily {self.daily_time}"
            return f"{self.daily_time} {','.join(WEEKDAY_NAMES[d] for d in self.weekdays)}"
        if self.recurring:
            return f"every {self.interval_minutes} min"
        return "once"

    def describe_status(self) -> str:
        """Status text for display, noting retries and a failed last run"""
        if self.status == TaskStatus.PENDING and self.attempt:
            return f"retrying ({self.attempt} failed)"
        if self.status == TaskStatus.PENDING and self.error_message:
            return "pending (last run failed)"
        return self.status.value

    def to_dict(self) -> Dict:
        """Convert task to dictionary"""
        return {
            'task_id': self.task_id,
            'task_type': self.task_type.value,
            'source_path': self.source_path,
            'dest_path': self.dest_path,
            'scheduled_time': self.scheduled_time.isoformat(),
            'recurring': self.recurring,
            'interval_minutes': self.interval_minutes,
            'daily_time': self.daily_time,
            'weekdays': self.weekdays,
            'server': self.server,
            'status': self.status.value,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'error_message': self.error_message,
            'attempt': self.attempt,
            'claim': self.claim,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ScheduledTask':
        """Create task from dictionary (2.0 files without the newer keys load too)"""
        task = cls(
            task_id=data['task_id'],
            task_type=TaskType(data['task_type']),
            source_path=data['source_path'],
            dest_path=data.get('dest_path', ''),
            scheduled_time=datetime.fromisoformat(data['scheduled_time']),
            recurring=data.get('recurring', False),
            interval_minutes=data.get('interval_minutes', 0),
            daily_time=data.get('daily_time', ''),
            weekdays=data.get('weekdays') or [],
            server=data.get('server', ''),
        )
        task.status = TaskStatus(data.get('status', 'pending'))
        task.last_run = datetime.fromisoformat(data['last_run']) if data.get('last_run') else None
        task.next_run = datetime.fromisoformat(data['next_run']) if data.get('next_run') else None
        task.error_message = data.get('error_message', '')
        task.attempt = int(data.get('attempt', 0))
        task.claim = data.get('claim')
        return task


def pid_alive(pid: int) -> bool:
    """
    Report whether a process exists on this machine.

    Never uses os.kill(pid, 0) on Windows: signal 0 is a console event there,
    and it raises winerror 87 for a live process that is not ours.

    Args:
        pid: Process id

    Returns:
        True when the process is running (or cannot be checked)
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FileLock:
    """
    Exclusive inter-process lock on a separate lock file (msvcrt on Windows,
    fcntl elsewhere). Re-entrant within one instance.
    """

    def __init__(self, path: str, timeout: float = 30.0):
        """
        Args:
            path: Lock file path (created if missing)
            timeout: Seconds to wait before giving up with TimeoutError
        """
        self.path = path
        self.timeout = timeout
        self._handle = None
        self._depth = 0

    def acquire(self) -> None:
        """Take the lock, waiting up to timeout seconds"""
        if self._depth:
            self._depth += 1
            return
        handle = open(self.path, 'a+')
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise TimeoutError(f"Another process holds {self.path}")
                time.sleep(0.05)
        self._handle = handle
        self._depth = 1

    def release(self) -> None:
        """Release one level of the lock"""
        if not self._depth:
            return
        self._depth -= 1
        if self._depth:
            return
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> 'FileLock':
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class TaskScheduler:
    """Manages scheduled tasks stored in a file shared between processes"""

    def __init__(self, tasks_file: str = "scheduled_tasks.json", check_interval: float = 10,
                 retries: int = 0, retry_delay: float = 60, runner: str = "app"):
        """
        Initialize task scheduler

        Args:
            tasks_file: Path to tasks storage file
            check_interval: Seconds between checks for due tasks
            retries: Extra attempts after a failed run
            retry_delay: Seconds before the first retry; doubles each time
            runner: Name recorded in the run history (gui, console, run-due)
        """
        self.tasks_file = tasks_file
        self.history_file = os.path.splitext(tasks_file)[0] + ".history.jsonl"
        self.check_interval = max(0.05, float(check_interval))
        self.retries = max(0, int(retries))
        self.retry_delay = max(0.0, float(retry_delay))
        self.runner = runner
        self.tasks: Dict[str, ScheduledTask] = {}
        self.scheduler_thread: Optional[threading.Thread] = None
        self.task_executor: Optional[Callable[[ScheduledTask], bool]] = None
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._file_lock = FileLock(tasks_file + ".lock")
        self._stop_event = threading.Event()
        self._token = uuid.uuid4().hex
        self._host = socket.gethostname().lower()  # host names are case-insensitive
        self._active_runs: set = set()
        self.load_tasks()

    @property
    def running(self) -> bool:
        """True while the scheduler thread is alive"""
        return bool(self.scheduler_thread and self.scheduler_thread.is_alive())

    def set_task_executor(self, executor: Callable[[ScheduledTask], bool]) -> None:
        """
        Set the function that executes tasks

        Args:
            executor: Callable that takes a ScheduledTask and returns True on
                success; raising marks the run failed with that message
        """
        self.task_executor = executor

    # ----- storage ------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the thread and file locks, with the tasks freshly read from disk"""
        with self._lock, self._file_lock:
            self._read(strict=True)
            yield

    def _read(self, strict: bool) -> None:
        """Replace in-memory tasks with the file's contents"""
        if not os.path.exists(self.tasks_file):
            self.tasks = {}
            return
        try:
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
        except Exception as e:
            message = f"Failed to load tasks from {self.tasks_file}: {e}"
            self.logger.error(message)
            if strict:
                # Never save over a file that could not be read.
                raise RuntimeError(message) from e
            return

        loaded: Dict[str, ScheduledTask] = {}
        for task_data in tasks_data:
            try:
                task = ScheduledTask.from_dict(task_data)
            except Exception as e:
                self.logger.error(f"Skipping unreadable task {task_data.get('task_id', '?')}: {e}")
                continue
            if task.status == TaskStatus.RUNNING and self._claim_is_stale(task.claim):
                task.status = TaskStatus.PENDING
                task.claim = None
                task.error_message = "Interrupted: the process running it stopped"
            loaded[task.task_id] = task
        self.tasks = loaded

    def _claim_is_stale(self, claim: Optional[Dict[str, Any]]) -> bool:
        if not claim:
            return True  # written by 2.0, or by a crash before claims existed
        if str(claim.get('host', '')).lower() == self._host:
            if claim.get('pid') == os.getpid():
                # This process: stale only if it was this instance that crashed
                # mid-run; other instances in the same process are still alive.
                return claim.get('token') == self._token and not self._is_running(claim)
            return not pid_alive(int(claim.get('pid', 0)))
        try:
            claimed_at = datetime.fromisoformat(claim.get('at', ''))
        except ValueError:
            return True
        return datetime.now() - claimed_at > FOREIGN_CLAIM_TIMEOUT

    def _is_running(self, claim: Dict[str, Any]) -> bool:
        return claim.get('run') in self._active_runs

    def _save(self) -> None:
        """Write tasks atomically (caller holds the locks)"""
        tasks_data = [task.to_dict() for task in self.tasks.values()]
        directory = os.path.dirname(os.path.abspath(self.tasks_file))
        fd, tmp_path = tempfile.mkstemp(prefix='.tasks-', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, indent=2)
            os.replace(tmp_path, self.tasks_file)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def load_tasks(self) -> None:
        """Load tasks from file (a read; an unreadable file is logged, not overwritten)"""
        with self._lock:
            self._read(strict=False)
        self.logger.info(f"Loaded {len(self.tasks)} tasks")

    def save_tasks(self) -> None:
        """Save the in-memory tasks (kept for callers of 2.0)"""
        with self._lock, self._file_lock:
            self._save()

    # ----- task management --------------------------------------------

    def add_task(self, task: ScheduledTask) -> None:
        """
        Add a new scheduled task

        Args:
            task: ScheduledTask to add
        """
        with self._locked():
            self.tasks[task.task_id] = task
            self._save()
        self.logger.info(f"Added task: {task.task_id}")

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a scheduled task

        Args:
            task_id: ID of task to remove

        Returns:
            True if removed, False if not found
        """
        with self._locked():
            if task_id not in self.tasks:
                return False
            del self.tasks[task_id]
            self._save()
        self.logger.info(f"Removed task: {task_id}")
        return True

    def find_task(self, id_prefix: str) -> Optional[ScheduledTask]:
        """
        Find a task by full ID or an unambiguous prefix

        Args:
            id_prefix: Full task ID or its start (at least 4 characters)

        Returns:
            The matching task, or None when nothing or more than one matches
        """
        id_prefix = id_prefix.strip()
        if len(id_prefix) < 4:
            return None
        tasks = {t.task_id: t for t in self.get_all_tasks()}
        if id_prefix in tasks:
            return tasks[id_prefix]
        matches = [t for t in tasks.values() if t.task_id.startswith(id_prefix)]
        return matches[0] if len(matches) == 1 else None

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a snapshot of a task by ID, read from disk"""
        with self._lock:
            self._read(strict=False)
            return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[ScheduledTask]:
        """Get a snapshot of all tasks from disk, soonest first"""
        with self._lock:
            self._read(strict=False)
            tasks = list(self.tasks.values())
        return sorted(tasks, key=lambda t: t.next_run or datetime.max)

    # ----- running ------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler"""
        if self.running:
            self.logger.warning("Scheduler already running")
            return

        self._stop_event.clear()
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop, name="sftp-pilot-scheduler", daemon=True
        )
        self.scheduler_thread.start()
        self.logger.info("Scheduler started")

    def stop(self, timeout: float = 5) -> None:
        """
        Stop the scheduler. A task already running finishes first.

        Args:
            timeout: Seconds to wait for the scheduler thread to finish
        """
        self._stop_event.set()
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=timeout)
            if self.scheduler_thread.is_alive():
                self.logger.warning("Scheduler is finishing a running task and will stop after it")
        self.logger.info("Scheduler stopped")

    def _scheduler_loop(self) -> None:
        """Main scheduler loop"""
        while not self._stop_event.is_set():
            try:
                self.run_due_tasks()
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
            self._stop_event.wait(self.check_interval)

    def run_due_tasks(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Claim and execute every pending task whose next run is due

        Args:
            now: Time to compare against (defaults to the current time)

        Returns:
            One history record per task executed (empty when nothing was due)
        """
        if not self.task_executor:
            self.logger.error("No task executor set")
            return []
        now = now or datetime.now()
        run_id = uuid.uuid4().hex
        # Registered before the claim is written, so a read in between never
        # mistakes this run's own claim for a crashed one.
        self._active_runs.add(run_id)
        try:
            return self._claim_and_run(run_id, now)
        finally:
            self._active_runs.discard(run_id)

    def _claim_and_run(self, run_id: str, now: datetime) -> List[Dict[str, Any]]:
        with self._locked():
            due = sorted((t for t in self.tasks.values()
                          if t.status == TaskStatus.PENDING and t.next_run and t.next_run <= now),
                         key=lambda t: t.next_run or now)
            for task in due:
                task.status = TaskStatus.RUNNING
                task.claim = {'host': self._host, 'pid': os.getpid(), 'token': self._token,
                              'run': run_id, 'at': datetime.now().isoformat()}
            if due:
                self._save()

        records = []
        for task in due:
            if self._stop_event.is_set():
                self._release(task, run_id)
                continue
            records.append(self._execute(task, run_id, now))
        return records

    def _release(self, task: ScheduledTask, run_id: str) -> None:
        """Hand a claimed but unstarted task back"""
        with self._locked():
            current = self.tasks.get(task.task_id)
            if current and current.claim and current.claim.get('run') == run_id:
                current.status = TaskStatus.PENDING
                current.claim = None
                self._save()

    def _execute(self, task: ScheduledTask, run_id: str, now: datetime) -> Dict[str, Any]:
        """Run one claimed task and record the outcome"""
        self.logger.info(f"Executing task: {task.task_id}")
        executor = self.task_executor
        started = time.monotonic()
        error = ""
        try:
            if executor is None or not executor(task):
                error = "Task execution failed (see log for details)"
        except Exception as e:
            error = str(e) or e.__class__.__name__
        duration = round(time.monotonic() - started, 3)
        finished = datetime.now()

        with self._locked():
            current = self.tasks.get(task.task_id)
            attempt = (current.attempt if current else task.attempt) + 1
            if current is not None and current.claim and current.claim.get('run') == run_id:
                self._finish(current, error, finished, max(now, finished))
                self._save()
            record = {
                'time': finished.isoformat(timespec='seconds'),
                'task_id': task.task_id,
                'type': task.task_type.value,
                'server': task.server_label,
                'source': task.source_path,
                'dest': task.dest_path,
                'result': 'failed' if error else 'ok',
                'error': error,
                'duration_s': duration,
                'attempt': attempt,
                'runner': self.runner,
            }
            self._append_history(record)

        if error:
            self.logger.error(f"Task failed: {task.task_id} - {error}")
        else:
            self.logger.info(f"Task completed: {task.task_id}")
        return record

    def _finish(self, task: ScheduledTask, error: str, finished: datetime, ref: datetime) -> None:
        """Apply a run's outcome: retry, reschedule, or close the task"""
        task.claim = None
        task.last_run = finished
        task.error_message = error
        if error and task.attempt < self.retries:
            task.attempt += 1
            delay = self.retry_delay * (2 ** (task.attempt - 1))
            task.next_run = finished + timedelta(seconds=delay)
            task.status = TaskStatus.PENDING
            self.logger.info(f"Task {task.task_id} retry {task.attempt} of {self.retries} at {task.next_run}")
            return
        task.attempt = 0
        if task.recurring:
            # A recurring task keeps its schedule after a failure, so one
            # network blip does not silently end a nightly job.
            task.next_run = task.following_run(ref)
            task.status = TaskStatus.PENDING
            self.logger.info(f"Task {task.task_id} will run again at {task.next_run}")
        else:
            task.status = TaskStatus.FAILED if error else TaskStatus.COMPLETED

    # ----- history ------------------------------------------------------

    def _append_history(self, record: Dict[str, Any]) -> None:
        """Append one run record (caller holds the file lock); rotate at 5 MB"""
        try:
            if os.path.exists(self.history_file) and os.path.getsize(self.history_file) > HISTORY_MAX_BYTES:
                os.replace(self.history_file, self.history_file + ".1")
            with open(self.history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            self.logger.error(f"Could not write run history: {e}")

    def read_history(self, task_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Read recent runs, newest first

        Args:
            task_id: Only runs of this task (full ID or prefix); '' for all
            limit: Maximum number of records

        Returns:
            History records
        """
        records: List[Dict[str, Any]] = []
        if not os.path.exists(self.history_file):
            return records
        with open(self.history_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut short by a crash
                if not task_id or str(record.get('task_id', '')).startswith(task_id):
                    records.append(record)
        return records[::-1][:limit]
