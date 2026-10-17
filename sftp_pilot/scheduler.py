"""
Task Scheduler for automated file operations

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional


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


class ScheduledTask:
    """Represents a scheduled task"""

    def __init__(self, task_id: str, task_type: TaskType,
                 source_path: str, dest_path: str = "",
                 scheduled_time: Optional[datetime] = None,
                 recurring: bool = False, interval_minutes: int = 0):
        """
        Initialize a scheduled task

        Args:
            task_id: Unique task identifier
            task_type: Type of task (upload, download, delete)
            source_path: Source file path
            dest_path: Destination path (for upload/download)
            scheduled_time: When to execute the task
            recurring: Whether task should repeat
            interval_minutes: Interval for recurring tasks (must be > 0 when recurring)

        Raises:
            ValueError: If the task definition is incomplete
        """
        if not source_path:
            raise ValueError("Source path is required")
        if task_type in (TaskType.UPLOAD, TaskType.DOWNLOAD) and not dest_path:
            raise ValueError(f"Destination path is required for {task_type.value} tasks")
        if recurring and interval_minutes <= 0:
            raise ValueError("Recurring tasks need an interval of at least 1 minute")

        self.task_id = task_id
        self.task_type = task_type
        self.source_path = source_path
        self.dest_path = dest_path
        self.scheduled_time = scheduled_time or datetime.now()
        self.recurring = recurring
        self.interval_minutes = interval_minutes if recurring else 0
        self.status = TaskStatus.PENDING
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = self.scheduled_time
        self.error_message = ""

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
            'status': self.status.value,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'error_message': self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ScheduledTask':
        """Create task from dictionary"""
        task = cls(
            task_id=data['task_id'],
            task_type=TaskType(data['task_type']),
            source_path=data['source_path'],
            dest_path=data.get('dest_path', ''),
            scheduled_time=datetime.fromisoformat(data['scheduled_time']),
            recurring=data.get('recurring', False),
            interval_minutes=data.get('interval_minutes', 0)
        )
        task.status = TaskStatus(data.get('status', 'pending'))
        task.last_run = datetime.fromisoformat(data['last_run']) if data.get('last_run') else None
        task.next_run = datetime.fromisoformat(data['next_run']) if data.get('next_run') else None
        task.error_message = data.get('error_message', '')
        return task

    def describe_status(self) -> str:
        """Status text for display, noting a failed last run of a recurring task"""
        if self.status == TaskStatus.PENDING and self.error_message:
            return "pending (last run failed)"
        return self.status.value


class TaskScheduler:
    """Manages scheduled tasks"""

    def __init__(self, tasks_file: str = "scheduled_tasks.json", check_interval: float = 10):
        """
        Initialize task scheduler

        Args:
            tasks_file: Path to tasks storage file
            check_interval: Seconds between checks for due tasks
        """
        self.tasks_file = tasks_file
        self.check_interval = max(0.05, float(check_interval))
        self.tasks: Dict[str, ScheduledTask] = {}
        self.scheduler_thread: Optional[threading.Thread] = None
        self.task_executor: Optional[Callable[[ScheduledTask], bool]] = None
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self.load_tasks()

    @property
    def running(self) -> bool:
        """True while the scheduler thread is alive"""
        return bool(self.scheduler_thread and self.scheduler_thread.is_alive())

    def set_task_executor(self, executor: Callable[[ScheduledTask], bool]) -> None:
        """
        Set the function that executes tasks

        Args:
            executor: Callable that takes a ScheduledTask and returns True on success
        """
        self.task_executor = executor

    def add_task(self, task: ScheduledTask) -> None:
        """
        Add a new scheduled task

        Args:
            task: ScheduledTask to add
        """
        with self._lock:
            self.tasks[task.task_id] = task
            self.save_tasks()
        self.logger.info(f"Added task: {task.task_id}")

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a scheduled task

        Args:
            task_id: ID of task to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if task_id not in self.tasks:
                return False
            del self.tasks[task_id]
            self.save_tasks()
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
        with self._lock:
            if id_prefix in self.tasks:
                return self.tasks[id_prefix]
            matches = [t for t in self.tasks.values() if t.task_id.startswith(id_prefix)]
        return matches[0] if len(matches) == 1 else None

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get task by ID"""
        with self._lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[ScheduledTask]:
        """Get all scheduled tasks, soonest first"""
        with self._lock:
            tasks = list(self.tasks.values())
        return sorted(tasks, key=lambda t: t.next_run or datetime.max)

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

    def run_due_tasks(self, now: Optional[datetime] = None) -> int:
        """
        Execute every pending task whose next run is due

        Args:
            now: Time to compare against (defaults to the current time)

        Returns:
            Number of tasks executed
        """
        now = now or datetime.now()
        with self._lock:
            due = [t for t in self.tasks.values()
                   if t.status == TaskStatus.PENDING and t.next_run and t.next_run <= now]
        due.sort(key=lambda t: t.next_run or now)
        for task in due:
            if self._stop_event.is_set():
                break
            self._execute_task(task)
        return len(due)

    def _execute_task(self, task: ScheduledTask) -> None:
        """
        Execute a scheduled task

        Args:
            task: Task to execute
        """
        if not self.task_executor:
            self.logger.error("No task executor set")
            return

        with self._lock:
            if task.task_id not in self.tasks:
                return  # removed while waiting
            task.status = TaskStatus.RUNNING
            self.save_tasks()
        self.logger.info(f"Executing task: {task.task_id}")

        error = ""
        try:
            if not self.task_executor(task):
                error = "Task execution failed (see log for details)"
        except Exception as e:
            error = str(e) or e.__class__.__name__

        with self._lock:
            task.last_run = datetime.now()
            task.error_message = error
            if task.recurring and task.interval_minutes > 0:
                # A recurring task keeps its schedule after a failure, so one
                # network blip does not silently end a nightly job.
                task.next_run = task.last_run + timedelta(minutes=task.interval_minutes)
                task.status = TaskStatus.PENDING
            else:
                task.status = TaskStatus.FAILED if error else TaskStatus.COMPLETED
            if task.task_id in self.tasks:
                self.save_tasks()

        if error:
            self.logger.error(f"Task failed: {task.task_id} - {error}")
        if task.status == TaskStatus.PENDING:
            self.logger.info(f"Task {task.task_id} will run again at {task.next_run}")
        elif not error:
            self.logger.info(f"Task completed: {task.task_id}")

    def save_tasks(self) -> None:
        """Save tasks to file atomically (write a temporary file, then replace)"""
        try:
            with self._lock:
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
        except Exception as e:
            self.logger.error(f"Failed to save tasks: {e}")

    def load_tasks(self) -> None:
        """Load tasks from file"""
        if not os.path.exists(self.tasks_file):
            return

        try:
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load tasks: {e}")
            return

        loaded: Dict[str, ScheduledTask] = {}
        for task_data in tasks_data:
            try:
                task = ScheduledTask.from_dict(task_data)
            except Exception as e:
                self.logger.error(f"Skipping unreadable task {task_data.get('task_id', '?')}: {e}")
                continue
            if task.status == TaskStatus.RUNNING:
                # The app stopped mid-run; without this the task never runs again.
                task.status = TaskStatus.PENDING
                task.error_message = "Interrupted: the application stopped while it was running"
            loaded[task.task_id] = task

        with self._lock:
            self.tasks = loaded
        self.logger.info(f"Loaded {len(loaded)} tasks")
