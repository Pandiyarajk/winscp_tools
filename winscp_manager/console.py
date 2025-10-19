"""
Console Interface for WinSCP Manager
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid

from .config_manager import ConfigManager
from .winscp_handler import WinSCPHandler
from .scheduler import TaskScheduler, ScheduledTask, TaskType, TaskStatus


class ConsoleInterface:
    """Console-based interface for WinSCP Manager"""
    
    def __init__(self):
        """Initialize console interface"""
        self.config_manager = None
        self.winscp_handler = None
        self.scheduler = None
        self.connected = False
        self.running = True
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def run(self):
        """Run the console interface"""
        print("=" * 60)
        print("WinSCP Manager - Console Interface")
        print("=" * 60)
        print()
        
        # Try to load config
        try:
            self.config_manager = ConfigManager()
            self.logger.info("Configuration loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {str(e)}")
            print("Warning: Could not load configuration file")
        
        # Initialize scheduler
        try:
            self.scheduler = TaskScheduler()
            self.scheduler.set_task_executor(self.execute_scheduled_task)
            self.logger.info("Scheduler initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize scheduler: {str(e)}")
        
        while self.running:
            self.show_menu()
            choice = input("\nEnter your choice: ").strip()
            self.handle_choice(choice)
    
    def show_menu(self):
        """Display main menu"""
        print("\n" + "=" * 60)
        print("Main Menu")
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
        if action:
            try:
                action()
            except Exception as e:
                self.logger.error(f"Error: {str(e)}")
                print(f"\nError: {str(e)}")
        else:
            print("\nInvalid choice. Please try again.")
    
    def connect(self):
        """Connect to server"""
        if self.connected:
            print("\nAlready connected to server")
            return
        
        if not self.config_manager:
            print("\nConfiguration not loaded. Cannot connect.")
            return
        
        try:
            conn_details = self.config_manager.get_connection_details()
            
            print(f"\nConnecting to {conn_details['host']}:{conn_details['port']}...")
            
            self.winscp_handler = WinSCPHandler(
                host=conn_details['host'],
                port=conn_details['port'],
                username=conn_details['username'],
                password=conn_details['password'],
                private_key_path=conn_details['private_key_path'],
                protocol=conn_details['protocol']
            )
            
            if self.winscp_handler.connect():
                self.connected = True
                print("✓ Connected successfully!")
            else:
                print("✗ Connection failed")
        except Exception as e:
            print(f"✗ Connection error: {str(e)}")
    
    def disconnect(self):
        """Disconnect from server"""
        if not self.connected:
            print("\nNot connected to server")
            return
        
        self.winscp_handler.disconnect()
        self.connected = False
        print("\n✓ Disconnected")
    
    def upload_file(self):
        """Upload file to server"""
        if not self.connected:
            print("\n✗ Not connected to server. Please connect first.")
            return
        
        local_path = input("\nEnter local file path: ").strip()
        remote_path = input("Enter remote destination path: ").strip()
        
        if not local_path or not remote_path:
            print("✗ Both paths are required")
            return
        
        print(f"\nUploading {local_path} to {remote_path}...")
        
        def progress_callback(sent, total):
            progress = (sent / total) * 100
            print(f"\rProgress: {progress:.1f}% ({sent}/{total} bytes)", end='', flush=True)
        
        if self.winscp_handler.upload_file(local_path, remote_path, progress_callback):
            print("\n✓ Upload completed successfully")
        else:
            print("\n✗ Upload failed")
    
    def download_file(self):
        """Download file from server"""
        if not self.connected:
            print("\n✗ Not connected to server. Please connect first.")
            return
        
        remote_path = input("\nEnter remote file path: ").strip()
        local_path = input("Enter local destination path: ").strip()
        
        if not remote_path or not local_path:
            print("✗ Both paths are required")
            return
        
        print(f"\nDownloading {remote_path} to {local_path}...")
        
        def progress_callback(received, total):
            progress = (received / total) * 100
            print(f"\rProgress: {progress:.1f}% ({received}/{total} bytes)", end='', flush=True)
        
        if self.winscp_handler.download_file(remote_path, local_path, progress_callback):
            print("\n✓ Download completed successfully")
        else:
            print("\n✗ Download failed")
    
    def delete_file(self):
        """Delete file from server"""
        if not self.connected:
            print("\n✗ Not connected to server. Please connect first.")
            return
        
        remote_path = input("\nEnter remote file path to delete: ").strip()
        
        if not remote_path:
            print("✗ Path is required")
            return
        
        confirm = input(f"Are you sure you want to delete {remote_path}? (yes/no): ").strip().lower()
        
        if confirm == 'yes':
            if self.winscp_handler.delete_file(remote_path):
                print("✓ File deleted successfully")
            else:
                print("✗ Delete failed")
        else:
            print("Cancelled")
    
    def list_files(self):
        """List files in remote directory"""
        if not self.connected:
            print("\n✗ Not connected to server. Please connect first.")
            return
        
        remote_path = input("\nEnter remote directory path (default: /): ").strip() or "/"
        
        files = self.winscp_handler.list_files(remote_path)
        
        if files:
            print(f"\nFiles in {remote_path}:")
            print("-" * 60)
            for file in files:
                print(f"  {file}")
            print("-" * 60)
        else:
            print("\nNo files found or error occurred")
    
    def schedule_task(self):
        """Schedule a new task"""
        if not self.scheduler:
            print("\n✗ Scheduler not initialized")
            return
        
        print("\nSchedule New Task")
        print("-" * 60)
        print("Task Types: 1) Upload  2) Download  3) Delete")
        task_choice = input("Select task type (1-3): ").strip()
        
        task_type_map = {'1': TaskType.UPLOAD, '2': TaskType.DOWNLOAD, '3': TaskType.DELETE}
        task_type = task_type_map.get(task_choice)
        
        if not task_type:
            print("✗ Invalid task type")
            return
        
        source_path = input("Enter source path: ").strip()
        dest_path = ""
        
        if task_type in [TaskType.UPLOAD, TaskType.DOWNLOAD]:
            dest_path = input("Enter destination path: ").strip()
        
        delay_minutes = int(input("Run in how many minutes? ").strip() or "5")
        
        recurring = input("Recurring task? (yes/no): ").strip().lower() == 'yes'
        interval_minutes = 0
        
        if recurring:
            interval_minutes = int(input("Interval in minutes: ").strip() or "60")
        
        task_id = str(uuid.uuid4())
        scheduled_time = datetime.now() + timedelta(minutes=delay_minutes)
        
        task = ScheduledTask(
            task_id=task_id,
            task_type=task_type,
            source_path=source_path,
            dest_path=dest_path,
            scheduled_time=scheduled_time,
            recurring=recurring,
            interval_minutes=interval_minutes
        )
        
        self.scheduler.add_task(task)
        print(f"\n✓ Task scheduled successfully (ID: {task_id[:8]}...)")
        print(f"  Will run at: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def view_tasks(self):
        """View all scheduled tasks"""
        if not self.scheduler:
            print("\n✗ Scheduler not initialized")
            return
        
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
            print(f"Destination: {task.dest_path if task.dest_path else 'N/A'}")
            print(f"Next Run: {task.next_run.strftime('%Y-%m-%d %H:%M:%S') if task.next_run else 'N/A'}")
            print(f"Status: {task.status.value}")
            print(f"Recurring: {'Yes' if task.recurring else 'No'}")
            if task.recurring:
                print(f"Interval: {task.interval_minutes} minutes")
            print("-" * 80)
    
    def remove_task(self):
        """Remove a scheduled task"""
        if not self.scheduler:
            print("\n✗ Scheduler not initialized")
            return
        
        task_id = input("\nEnter task ID to remove: ").strip()
        
        # Try to find task by full ID or partial ID
        for task in self.scheduler.get_all_tasks():
            if task.task_id == task_id or task.task_id.startswith(task_id):
                if self.scheduler.remove_task(task.task_id):
                    print(f"✓ Task {task.task_id[:8]}... removed")
                else:
                    print("✗ Failed to remove task")
                return
        
        print("✗ Task not found")
    
    def start_scheduler(self):
        """Start the scheduler"""
        if not self.scheduler:
            print("\n✗ Scheduler not initialized")
            return
        
        if self.scheduler.running:
            print("\nScheduler is already running")
            return
        
        self.scheduler.start()
        print("\n✓ Scheduler started")
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        if not self.scheduler:
            print("\n✗ Scheduler not initialized")
            return
        
        if not self.scheduler.running:
            print("\nScheduler is not running")
            return
        
        self.scheduler.stop()
        print("\n✓ Scheduler stopped")
    
    def execute_scheduled_task(self, task: ScheduledTask) -> bool:
        """Execute a scheduled task"""
        try:
            # Ensure connection
            if not self.connected:
                self.logger.info("Attempting to connect for scheduled task...")
                if not self.winscp_handler:
                    conn_details = self.config_manager.get_connection_details()
                    self.winscp_handler = WinSCPHandler(
                        conn_details['host'],
                        conn_details['port'],
                        conn_details['username'],
                        conn_details['password']
                    )
                
                if not self.winscp_handler.connect():
                    self.logger.error("Failed to connect for scheduled task")
                    return False
                self.connected = True
            
            # Execute task based on type
            if task.task_type == TaskType.UPLOAD:
                return self.winscp_handler.upload_file(task.source_path, task.dest_path)
            elif task.task_type == TaskType.DOWNLOAD:
                return self.winscp_handler.download_file(task.source_path, task.dest_path)
            elif task.task_type == TaskType.DELETE:
                return self.winscp_handler.delete_file(task.source_path)
            
            return False
        except Exception as e:
            self.logger.error(f"Task execution error: {str(e)}")
            return False
    
    def exit_app(self):
        """Exit the application"""
        print("\nExiting...")
        
        # Stop scheduler if running
        if self.scheduler and self.scheduler.running:
            self.scheduler.stop()
        
        # Disconnect if connected
        if self.connected:
            self.winscp_handler.disconnect()
        
        self.running = False
        print("Goodbye!")


def run_console():
    """Run the console interface"""
    console = ConsoleInterface()
    console.run()
