"""
GUI Interface for WinSCP Manager using tkinter
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime, timedelta
import threading
import logging
from typing import Optional
import uuid

from .config_manager import ConfigManager
from .winscp_handler import WinSCPHandler
from .scheduler import TaskScheduler, ScheduledTask, TaskType, TaskStatus


class WinSCPManagerGUI:
    """Main GUI application"""
    
    def __init__(self, root: tk.Tk):
        """
        Initialize GUI
        
        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title("WinSCP Manager - File Transfer & Scheduler")
        self.root.geometry("1000x700")
        
        # Initialize components
        self.config_manager = None
        self.winscp_handler = None
        self.scheduler = None
        self.connected = False
        
        # Setup logging
        self.setup_logging()
        
        # Create GUI
        self.create_widgets()
        
        # Try to load config
        self.load_configuration()
    
    def setup_logging(self):
        """Setup logging configuration"""
        self.logger = logging.getLogger(__name__)
        
    def create_widgets(self):
        """Create GUI widgets"""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Create tabs
        self.create_connection_tab()
        self.create_file_operations_tab()
        self.create_scheduler_tab()
        self.create_log_tab()
        
        # Status bar
        self.status_bar = tk.Label(self.root, text="Disconnected", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def create_connection_tab(self):
        """Create connection settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Connection")
        
        # Connection frame
        conn_frame = ttk.LabelFrame(tab, text="Connection Settings", padding=10)
        conn_frame.pack(fill='x', padx=10, pady=10)
        
        # Host
        ttk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky='w', pady=5)
        self.host_entry = ttk.Entry(conn_frame, width=40)
        self.host_entry.grid(row=0, column=1, padx=5, pady=5)
        
        # Port
        ttk.Label(conn_frame, text="Port:").grid(row=1, column=0, sticky='w', pady=5)
        self.port_entry = ttk.Entry(conn_frame, width=40)
        self.port_entry.grid(row=1, column=1, padx=5, pady=5)
        
        # Username
        ttk.Label(conn_frame, text="Username:").grid(row=2, column=0, sticky='w', pady=5)
        self.username_entry = ttk.Entry(conn_frame, width=40)
        self.username_entry.grid(row=2, column=1, padx=5, pady=5)
        
        # Password
        ttk.Label(conn_frame, text="Password:").grid(row=3, column=0, sticky='w', pady=5)
        self.password_entry = ttk.Entry(conn_frame, width=40, show="*")
        self.password_entry.grid(row=3, column=1, padx=5, pady=5)
        
        # Protocol
        ttk.Label(conn_frame, text="Protocol:").grid(row=4, column=0, sticky='w', pady=5)
        self.protocol_var = tk.StringVar(value="sftp")
        protocol_combo = ttk.Combobox(conn_frame, textvariable=self.protocol_var, 
                                      values=["sftp", "scp"], state="readonly", width=37)
        protocol_combo.grid(row=4, column=1, padx=5, pady=5)
        
        # Buttons
        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)
        
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side='left', padx=5)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", 
                                        command=self.disconnect, state='disabled')
        self.disconnect_btn.pack(side='left', padx=5)
        
        ttk.Button(btn_frame, text="Load Config", command=self.load_configuration).pack(side='left', padx=5)
    
    def create_file_operations_tab(self):
        """Create file operations tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="File Operations")
        
        # Upload frame
        upload_frame = ttk.LabelFrame(tab, text="Upload File", padding=10)
        upload_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(upload_frame, text="Local File:").grid(row=0, column=0, sticky='w', pady=5)
        self.upload_local_entry = ttk.Entry(upload_frame, width=50)
        self.upload_local_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(upload_frame, text="Browse", 
                  command=lambda: self.browse_file(self.upload_local_entry)).grid(row=0, column=2, padx=5)
        
        ttk.Label(upload_frame, text="Remote Path:").grid(row=1, column=0, sticky='w', pady=5)
        self.upload_remote_entry = ttk.Entry(upload_frame, width=50)
        self.upload_remote_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Button(upload_frame, text="Upload", command=self.upload_file).grid(row=2, column=1, pady=10)
        
        # Download frame
        download_frame = ttk.LabelFrame(tab, text="Download File", padding=10)
        download_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(download_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.download_remote_entry = ttk.Entry(download_frame, width=50)
        self.download_remote_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(download_frame, text="Local File:").grid(row=1, column=0, sticky='w', pady=5)
        self.download_local_entry = ttk.Entry(download_frame, width=50)
        self.download_local_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(download_frame, text="Browse", 
                  command=lambda: self.browse_save_file(self.download_local_entry)).grid(row=1, column=2, padx=5)
        
        ttk.Button(download_frame, text="Download", command=self.download_file).grid(row=2, column=1, pady=10)
        
        # Delete frame
        delete_frame = ttk.LabelFrame(tab, text="Delete File", padding=10)
        delete_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(delete_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.delete_remote_entry = ttk.Entry(delete_frame, width=50)
        self.delete_remote_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Button(delete_frame, text="Delete", command=self.delete_file).grid(row=1, column=1, pady=10)
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(tab, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', padx=10, pady=10)
        
        self.progress_label = ttk.Label(tab, text="")
        self.progress_label.pack()
    
    def create_scheduler_tab(self):
        """Create scheduler tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Scheduler")
        
        # Add task frame
        add_frame = ttk.LabelFrame(tab, text="Add Scheduled Task", padding=10)
        add_frame.pack(fill='x', padx=10, pady=10)
        
        # Task type
        ttk.Label(add_frame, text="Task Type:").grid(row=0, column=0, sticky='w', pady=5)
        self.task_type_var = tk.StringVar(value="upload")
        task_type_combo = ttk.Combobox(add_frame, textvariable=self.task_type_var,
                                       values=["upload", "download", "delete"], 
                                       state="readonly", width=37)
        task_type_combo.grid(row=0, column=1, padx=5, pady=5)
        
        # Source path
        ttk.Label(add_frame, text="Source Path:").grid(row=1, column=0, sticky='w', pady=5)
        self.task_source_entry = ttk.Entry(add_frame, width=40)
        self.task_source_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(add_frame, text="Browse", 
                  command=lambda: self.browse_file(self.task_source_entry)).grid(row=1, column=2, padx=5)
        
        # Destination path
        ttk.Label(add_frame, text="Dest Path:").grid(row=2, column=0, sticky='w', pady=5)
        self.task_dest_entry = ttk.Entry(add_frame, width=40)
        self.task_dest_entry.grid(row=2, column=1, padx=5, pady=5)
        
        # Schedule time
        ttk.Label(add_frame, text="Run In (minutes):").grid(row=3, column=0, sticky='w', pady=5)
        self.task_delay_entry = ttk.Entry(add_frame, width=40)
        self.task_delay_entry.insert(0, "5")
        self.task_delay_entry.grid(row=3, column=1, padx=5, pady=5)
        
        # Recurring
        self.recurring_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(add_frame, text="Recurring Task", 
                       variable=self.recurring_var).grid(row=4, column=1, sticky='w', pady=5)
        
        # Interval
        ttk.Label(add_frame, text="Interval (minutes):").grid(row=5, column=0, sticky='w', pady=5)
        self.task_interval_entry = ttk.Entry(add_frame, width=40)
        self.task_interval_entry.insert(0, "60")
        self.task_interval_entry.grid(row=5, column=1, padx=5, pady=5)
        
        ttk.Button(add_frame, text="Add Task", command=self.add_scheduled_task).grid(row=6, column=1, pady=10)
        
        # Tasks list
        list_frame = ttk.LabelFrame(tab, text="Scheduled Tasks", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create treeview
        columns = ('ID', 'Type', 'Source', 'Destination', 'Next Run', 'Status')
        self.tasks_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.tasks_tree.heading(col, text=col)
            self.tasks_tree.column(col, width=150)
        
        self.tasks_tree.pack(fill='both', expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.tasks_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tasks_tree.configure(yscrollcommand=scrollbar.set)
        
        # Buttons
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill='x', pady=5)
        
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_tasks).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_selected_task).pack(side='left', padx=5)
        
        # Scheduler control
        control_frame = ttk.Frame(list_frame)
        control_frame.pack(fill='x', pady=5)
        
        self.scheduler_btn = ttk.Button(control_frame, text="Start Scheduler", command=self.toggle_scheduler)
        self.scheduler_btn.pack(side='left', padx=5)
        
        self.scheduler_status_label = ttk.Label(control_frame, text="Scheduler: Stopped")
        self.scheduler_status_label.pack(side='left', padx=5)
    
    def create_log_tab(self):
        """Create log viewer tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Logs")
        
        self.log_text = scrolledtext.ScrolledText(tab, wrap=tk.WORD, height=30)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Configure text handler for logging
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(text_handler)
        logging.getLogger().setLevel(logging.INFO)
    
    def browse_file(self, entry_widget):
        """Browse for file"""
        filename = filedialog.askopenfilename()
        if filename:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, filename)
    
    def browse_save_file(self, entry_widget):
        """Browse for save location"""
        filename = filedialog.asksaveasfilename()
        if filename:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, filename)
    
    def load_configuration(self):
        """Load configuration from file"""
        try:
            self.config_manager = ConfigManager()
            conn_details = self.config_manager.get_connection_details()
            
            self.host_entry.delete(0, tk.END)
            self.host_entry.insert(0, conn_details.get('host', ''))
            
            self.port_entry.delete(0, tk.END)
            self.port_entry.insert(0, str(conn_details.get('port', 22)))
            
            self.username_entry.delete(0, tk.END)
            self.username_entry.insert(0, conn_details.get('username', ''))
            
            self.password_entry.delete(0, tk.END)
            self.password_entry.insert(0, conn_details.get('password', ''))
            
            self.protocol_var.set(conn_details.get('protocol', 'sftp'))
            
            # Initialize scheduler
            self.scheduler = TaskScheduler()
            self.scheduler.set_task_executor(self.execute_scheduled_task)
            
            self.log("Configuration loaded successfully")
        except Exception as e:
            self.log(f"Failed to load configuration: {str(e)}", "ERROR")
    
    def connect(self):
        """Connect to remote server"""
        try:
            host = self.host_entry.get()
            port = int(self.port_entry.get())
            username = self.username_entry.get()
            password = self.password_entry.get()
            protocol = self.protocol_var.get()
            
            if not host or not username:
                messagebox.showerror("Error", "Host and username are required")
                return
            
            self.log(f"Connecting to {host}:{port}...")
            
            self.winscp_handler = WinSCPHandler(host, port, username, password, '', protocol)
            
            if self.winscp_handler.connect():
                self.connected = True
                self.connect_btn.config(state='disabled')
                self.disconnect_btn.config(state='normal')
                self.status_bar.config(text=f"Connected to {host}:{port}")
                self.log("Connection successful")
                messagebox.showinfo("Success", "Connected successfully!")
            else:
                messagebox.showerror("Error", "Connection failed")
        except Exception as e:
            self.log(f"Connection error: {str(e)}", "ERROR")
            messagebox.showerror("Error", f"Connection failed: {str(e)}")
    
    def disconnect(self):
        """Disconnect from server"""
        if self.winscp_handler:
            self.winscp_handler.disconnect()
            self.connected = False
            self.connect_btn.config(state='normal')
            self.disconnect_btn.config(state='disabled')
            self.status_bar.config(text="Disconnected")
            self.log("Disconnected")
    
    def upload_file(self):
        """Upload file"""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to server")
            return
        
        local_path = self.upload_local_entry.get()
        remote_path = self.upload_remote_entry.get()
        
        if not local_path or not remote_path:
            messagebox.showerror("Error", "Both local and remote paths are required")
            return
        
        def upload_thread():
            self.log(f"Uploading {local_path} to {remote_path}...")
            
            def progress_callback(sent, total):
                progress = (sent / total) * 100
                self.progress_var.set(progress)
                self.progress_label.config(text=f"Uploading: {sent}/{total} bytes ({progress:.1f}%)")
            
            if self.winscp_handler.upload_file(local_path, remote_path, progress_callback):
                self.log("Upload completed successfully")
                messagebox.showinfo("Success", "File uploaded successfully!")
            else:
                messagebox.showerror("Error", "Upload failed")
            
            self.progress_var.set(0)
            self.progress_label.config(text="")
        
        threading.Thread(target=upload_thread, daemon=True).start()
    
    def download_file(self):
        """Download file"""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to server")
            return
        
        remote_path = self.download_remote_entry.get()
        local_path = self.download_local_entry.get()
        
        if not remote_path or not local_path:
            messagebox.showerror("Error", "Both remote and local paths are required")
            return
        
        def download_thread():
            self.log(f"Downloading {remote_path} to {local_path}...")
            
            def progress_callback(received, total):
                progress = (received / total) * 100
                self.progress_var.set(progress)
                self.progress_label.config(text=f"Downloading: {received}/{total} bytes ({progress:.1f}%)")
            
            if self.winscp_handler.download_file(remote_path, local_path, progress_callback):
                self.log("Download completed successfully")
                messagebox.showinfo("Success", "File downloaded successfully!")
            else:
                messagebox.showerror("Error", "Download failed")
            
            self.progress_var.set(0)
            self.progress_label.config(text="")
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def delete_file(self):
        """Delete remote file"""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to server")
            return
        
        remote_path = self.delete_remote_entry.get()
        
        if not remote_path:
            messagebox.showerror("Error", "Remote path is required")
            return
        
        if messagebox.askyesno("Confirm", f"Delete {remote_path}?"):
            if self.winscp_handler.delete_file(remote_path):
                self.log(f"Deleted {remote_path}")
                messagebox.showinfo("Success", "File deleted successfully!")
            else:
                messagebox.showerror("Error", "Delete failed")
    
    def add_scheduled_task(self):
        """Add a new scheduled task"""
        try:
            task_type = TaskType(self.task_type_var.get())
            source_path = self.task_source_entry.get()
            dest_path = self.task_dest_entry.get()
            delay_minutes = int(self.task_delay_entry.get())
            recurring = self.recurring_var.get()
            interval_minutes = int(self.task_interval_entry.get()) if recurring else 0
            
            if not source_path:
                messagebox.showerror("Error", "Source path is required")
                return
            
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
            
            if not self.scheduler:
                self.scheduler = TaskScheduler()
                self.scheduler.set_task_executor(self.execute_scheduled_task)
            
            self.scheduler.add_task(task)
            self.log(f"Added scheduled task: {task_id}")
            self.refresh_tasks()
            messagebox.showinfo("Success", "Task scheduled successfully!")
            
        except Exception as e:
            self.log(f"Failed to add task: {str(e)}", "ERROR")
            messagebox.showerror("Error", f"Failed to add task: {str(e)}")
    
    def execute_scheduled_task(self, task: ScheduledTask) -> bool:
        """Execute a scheduled task"""
        try:
            # Ensure connection
            if not self.connected:
                self.log("Attempting to connect for scheduled task...")
                # Try to connect using saved config
                if not self.winscp_handler:
                    conn_details = self.config_manager.get_connection_details()
                    self.winscp_handler = WinSCPHandler(
                        conn_details['host'],
                        conn_details['port'],
                        conn_details['username'],
                        conn_details['password']
                    )
                
                if not self.winscp_handler.connect():
                    self.log("Failed to connect for scheduled task", "ERROR")
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
            self.log(f"Task execution error: {str(e)}", "ERROR")
            return False
    
    def refresh_tasks(self):
        """Refresh tasks list"""
        if not self.scheduler:
            return
        
        # Clear current items
        for item in self.tasks_tree.get_children():
            self.tasks_tree.delete(item)
        
        # Add tasks
        for task in self.scheduler.get_all_tasks():
            self.tasks_tree.insert('', 'end', values=(
                task.task_id[:8],
                task.task_type.value,
                task.source_path[:30],
                task.dest_path[:30] if task.dest_path else 'N/A',
                task.next_run.strftime('%Y-%m-%d %H:%M') if task.next_run else 'N/A',
                task.status.value
            ))
    
    def remove_selected_task(self):
        """Remove selected task"""
        selection = self.tasks_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No task selected")
            return
        
        item = self.tasks_tree.item(selection[0])
        task_id_short = item['values'][0]
        
        # Find full task ID
        for task in self.scheduler.get_all_tasks():
            if task.task_id.startswith(task_id_short):
                if self.scheduler.remove_task(task.task_id):
                    self.log(f"Removed task: {task.task_id}")
                    self.refresh_tasks()
                    break
    
    def toggle_scheduler(self):
        """Start/stop scheduler"""
        if not self.scheduler:
            messagebox.showerror("Error", "Scheduler not initialized")
            return
        
        if self.scheduler.running:
            self.scheduler.stop()
            self.scheduler_btn.config(text="Start Scheduler")
            self.scheduler_status_label.config(text="Scheduler: Stopped")
            self.log("Scheduler stopped")
        else:
            self.scheduler.start()
            self.scheduler_btn.config(text="Stop Scheduler")
            self.scheduler_status_label.config(text="Scheduler: Running")
            self.log("Scheduler started")
    
    def log(self, message: str, level: str = "INFO"):
        """Log message"""
        if level == "ERROR":
            logging.error(message)
        else:
            logging.info(message)


class TextHandler(logging.Handler):
    """Custom logging handler for tkinter Text widget"""
    
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget
    
    def emit(self, record):
        msg = self.format(record)
        
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
        
        self.text_widget.after(0, append)


def run_gui():
    """Run the GUI application"""
    root = tk.Tk()
    app = WinSCPManagerGUI(root)
    root.mainloop()
