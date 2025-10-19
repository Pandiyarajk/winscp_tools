"""
Task Scheduler for automated file operations
"""

import json
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from enum import Enum


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
            interval_minutes: Interval for recurring tasks
        """
        self.task_id = task_id
        self.task_type = task_type
        self.source_path = source_path
        self.dest_path = dest_path
        self.scheduled_time = scheduled_time or datetime.now()
        self.recurring = recurring
        self.interval_minutes = interval_minutes
        self.status = TaskStatus.PENDING
        self.last_run = None
        self.next_run = self.scheduled_time
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


class TaskScheduler:
    """Manages scheduled tasks"""
    
    def __init__(self, tasks_file: str = "scheduled_tasks.json"):
        """
        Initialize task scheduler
        
        Args:
            tasks_file: Path to tasks storage file
        """
        self.tasks_file = tasks_file
        self.tasks: Dict[str, ScheduledTask] = {}
        self.running = False
        self.scheduler_thread = None
        self.task_executor: Optional[Callable] = None
        self.logger = logging.getLogger(__name__)
        self.load_tasks()
    
    def set_task_executor(self, executor: Callable) -> None:
        """
        Set the function that executes tasks
        
        Args:
            executor: Callable that takes a ScheduledTask and executes it
        """
        self.task_executor = executor
    
    def add_task(self, task: ScheduledTask) -> None:
        """
        Add a new scheduled task
        
        Args:
            task: ScheduledTask to add
        """
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
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.save_tasks()
            self.logger.info(f"Removed task: {task_id}")
            return True
        return False
    
    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get task by ID"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[ScheduledTask]:
        """Get all scheduled tasks"""
        return list(self.tasks.values())
    
    def start(self) -> None:
        """Start the scheduler"""
        if self.running:
            self.logger.warning("Scheduler already running")
            return
        
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        self.logger.info("Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        self.logger.info("Scheduler stopped")
    
    def _scheduler_loop(self) -> None:
        """Main scheduler loop"""
        while self.running:
            try:
                self._check_and_execute_tasks()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                self.logger.error(f"Scheduler error: {str(e)}")
    
    def _check_and_execute_tasks(self) -> None:
        """Check for due tasks and execute them"""
        now = datetime.now()
        
        for task in list(self.tasks.values()):
            if task.status == TaskStatus.PENDING and task.next_run <= now:
                self._execute_task(task)
    
    def _execute_task(self, task: ScheduledTask) -> None:
        """
        Execute a scheduled task
        
        Args:
            task: Task to execute
        """
        if not self.task_executor:
            self.logger.error("No task executor set")
            return
        
        task.status = TaskStatus.RUNNING
        self.logger.info(f"Executing task: {task.task_id}")
        
        try:
            # Execute the task using the provided executor
            success = self.task_executor(task)
            
            if success:
                task.status = TaskStatus.COMPLETED
                task.last_run = datetime.now()
                
                # Handle recurring tasks
                if task.recurring and task.interval_minutes > 0:
                    task.next_run = datetime.now() + timedelta(minutes=task.interval_minutes)
                    task.status = TaskStatus.PENDING
                    self.logger.info(f"Task {task.task_id} will run again at {task.next_run}")
                else:
                    self.logger.info(f"Task completed: {task.task_id}")
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "Task execution failed"
                self.logger.error(f"Task failed: {task.task_id}")
        
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            self.logger.error(f"Task error: {task.task_id} - {str(e)}")
        
        self.save_tasks()
    
    def save_tasks(self) -> None:
        """Save tasks to file"""
        try:
            tasks_data = [task.to_dict() for task in self.tasks.values()]
            with open(self.tasks_file, 'w') as f:
                json.dump(tasks_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save tasks: {str(e)}")
    
    def load_tasks(self) -> None:
        """Load tasks from file"""
        if not os.path.exists(self.tasks_file):
            return
        
        try:
            with open(self.tasks_file, 'r') as f:
                tasks_data = json.load(f)
            
            self.tasks = {}
            for task_data in tasks_data:
                task = ScheduledTask.from_dict(task_data)
                self.tasks[task.task_id] = task
            
            self.logger.info(f"Loaded {len(self.tasks)} tasks")
        except Exception as e:
            self.logger.error(f"Failed to load tasks: {str(e)}")
