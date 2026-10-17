"""
Runs scheduled tasks for both interfaces.

Each run opens its own connection from the saved configuration. Sharing the
interactive connection would put two threads on one SFTP channel (paramiko
does not support that) and would fail for good once that connection dropped.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

import logging
from typing import Any, Callable, Dict

from .scheduler import ScheduledTask, TaskType
from .sftp_handler import SFTPHandler

logger = logging.getLogger(__name__)


def run_task(handler: SFTPHandler, task: ScheduledTask) -> bool:
    """
    Perform one task on a connected handler

    Args:
        handler: A connected SFTPHandler
        task: The task to perform

    Returns:
        True on success
    """
    if task.task_type == TaskType.UPLOAD:
        return handler.upload_file(task.source_path, task.dest_path)
    if task.task_type == TaskType.DOWNLOAD:
        return handler.download_file(task.source_path, task.dest_path)
    if task.task_type == TaskType.DELETE:
        return handler.delete_file(task.source_path)
    return False


def make_task_executor(
    get_connection_details: Callable[[], Dict[str, Any]],
    handler_factory: Callable[[Dict[str, Any]], SFTPHandler] = SFTPHandler.from_config,
) -> Callable[[ScheduledTask], bool]:
    """
    Build a scheduler executor that connects, runs one task and disconnects

    Args:
        get_connection_details: Returns current connection details (read per run,
            so a config reload takes effect without restarting the scheduler)
        handler_factory: Builds a handler from connection details

    Returns:
        A callable suitable for TaskScheduler.set_task_executor
    """
    def execute(task: ScheduledTask) -> bool:
        handler = handler_factory(get_connection_details())
        if not handler.connect():
            raise ConnectionError(f"Could not connect for scheduled task: {handler.last_error}")
        try:
            return run_task(handler, task)
        finally:
            handler.disconnect()

    return execute
