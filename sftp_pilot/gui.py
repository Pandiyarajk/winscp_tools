"""
GUI Interface for SFTP Pilot using tkinter

Tk is single-threaded: worker threads never touch a widget. They post
callables to `self._ui_queue`, which the main loop drains every 100 ms.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import logging
import queue
import threading
import tkinter as tk
import uuid
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable, Optional

from .config_manager import ConfigManager
from .runner import make_task_executor
from .scheduler import ScheduledTask, TaskScheduler, TaskType
from .sftp_handler import SFTPHandler

UI_POLL_MS = 100
TASKS_REFRESH_MS = 5000


class SFTPPilotGUI:
    """Main GUI application"""

    def __init__(self, root: tk.Tk, config_path: str = "config.ini",
                 tasks_file: str = "scheduled_tasks.json"):
        """
        Initialize GUI

        Args:
            root: Tkinter root window
            config_path: Configuration file to read
            tasks_file: Where scheduled tasks are stored
        """
        self.root = root
        self.root.title("SFTP Pilot - File Transfer & Scheduler")
        self.root.geometry("1000x720")

        self.config_path = config_path
        self.config_manager: Optional[ConfigManager] = None
        self.sftp_handler: Optional[SFTPHandler] = None
        self.scheduler = TaskScheduler(tasks_file)
        self.busy = False
        self.logger = logging.getLogger(__name__)

        self._ui_queue: "queue.Queue[Callable[[], object]]" = queue.Queue()

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(UI_POLL_MS, self._drain_ui_queue)
        self.root.after(TASKS_REFRESH_MS, self._periodic_refresh)

        self.load_configuration()
        self.refresh_tasks()

    # ----- thread hand-off ------------------------------------------------

    def ui(self, fn: Callable[..., object], *args) -> None:
        """Run fn(*args) on the Tk main thread (safe from any thread)"""
        self._ui_queue.put(lambda: fn(*args))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception as e:
            self.logger.error(f"UI update failed: {e}")
        self.root.after(UI_POLL_MS, self._drain_ui_queue)

    def _periodic_refresh(self) -> None:
        self.refresh_tasks()
        if self.sftp_handler and not self.sftp_handler.is_connected():
            self.logger.warning("Connection lost")
            self.sftp_handler = None
            self._set_connected_state(False)
        self.root.after(TASKS_REFRESH_MS, self._periodic_refresh)

    def run_in_background(self, work: Callable[[], None]) -> None:
        """Run work on a daemon thread, one operation at a time"""
        if self.busy:
            messagebox.showwarning("Busy", "Another operation is still running")
            return
        self.busy = True

        def wrapper():
            try:
                work()
            except Exception as e:
                self.logger.error(f"Operation failed: {e}")
                self.ui(messagebox.showerror, "Error", str(e))
            finally:
                self.ui(self._finish_operation)

        threading.Thread(target=wrapper, daemon=True).start()

    def _finish_operation(self) -> None:
        self.busy = False
        self.progress_var.set(0)
        self.progress_label.config(text="")

    # ----- layout ---------------------------------------------------------

    def create_widgets(self):
        """Create GUI widgets"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        self.create_connection_tab()
        self.create_file_operations_tab()
        self.create_scheduler_tab()
        self.create_log_tab()

        self.status_bar = tk.Label(self.root, text="Disconnected", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_connection_tab(self):
        """Create connection settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Connection")

        conn_frame = ttk.LabelFrame(tab, text="Connection Settings (SFTP)", padding=10)
        conn_frame.pack(fill='x', padx=10, pady=10)

        def row(r: int, label: str, show: str = "") -> ttk.Entry:
            ttk.Label(conn_frame, text=label).grid(row=r, column=0, sticky='w', pady=5)
            entry = ttk.Entry(conn_frame, width=50, show=show)
            entry.grid(row=r, column=1, padx=5, pady=5, sticky='w')
            return entry

        self.host_entry = row(0, "Host:")
        self.port_entry = row(1, "Port:")
        self.username_entry = row(2, "Username:")
        self.password_entry = row(3, "Password:", show="*")
        self.key_entry = row(4, "Private key (optional):")
        ttk.Button(conn_frame, text="Browse",
                   command=lambda: self.browse_file(self.key_entry)).grid(row=4, column=2, padx=5)
        self.passphrase_entry = row(5, "Key passphrase:", show="*")

        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=6, column=0, columnspan=3, pady=10)

        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side='left', padx=5)

        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect",
                                         command=self.disconnect, state='disabled')
        self.disconnect_btn.pack(side='left', padx=5)

        ttk.Button(btn_frame, text="Reload Config", command=self.load_configuration).pack(side='left', padx=5)

        ttk.Label(tab, foreground='gray', wraplength=900, text=(
            "Host keys: a new server is remembered on first connect (known_hosts file); "
            "a server whose key later changes is refused. Scheduled tasks always connect "
            "with the settings saved in the configuration file, not the fields above."
        )).pack(fill='x', padx=12)

    def create_file_operations_tab(self):
        """Create file operations tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="File Operations")

        upload_frame = ttk.LabelFrame(tab, text="Upload File", padding=10)
        upload_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(upload_frame, text="Local File:").grid(row=0, column=0, sticky='w', pady=5)
        self.upload_local_entry = ttk.Entry(upload_frame, width=60)
        self.upload_local_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(upload_frame, text="Browse",
                   command=lambda: self.browse_file(self.upload_local_entry)).grid(row=0, column=2, padx=5)

        ttk.Label(upload_frame, text="Remote Path:").grid(row=1, column=0, sticky='w', pady=5)
        self.upload_remote_entry = ttk.Entry(upload_frame, width=60)
        self.upload_remote_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Label(upload_frame, text="(end with / for a folder)").grid(row=1, column=2, sticky='w')

        ttk.Button(upload_frame, text="Upload", command=self.upload_file).grid(row=2, column=1, pady=10)

        download_frame = ttk.LabelFrame(tab, text="Download File", padding=10)
        download_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(download_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.download_remote_entry = ttk.Entry(download_frame, width=60)
        self.download_remote_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(download_frame, text="Local File:").grid(row=1, column=0, sticky='w', pady=5)
        self.download_local_entry = ttk.Entry(download_frame, width=60)
        self.download_local_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(download_frame, text="Browse",
                   command=lambda: self.browse_save_file(self.download_local_entry)).grid(row=1, column=2, padx=5)

        ttk.Button(download_frame, text="Download", command=self.download_file).grid(row=2, column=1, pady=10)

        delete_frame = ttk.LabelFrame(tab, text="Delete File", padding=10)
        delete_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(delete_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.delete_remote_entry = ttk.Entry(delete_frame, width=60)
        self.delete_remote_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Button(delete_frame, text="Delete", command=self.delete_file).grid(row=1, column=1, pady=10)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(tab, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', padx=10, pady=10)

        self.progress_label = ttk.Label(tab, text="")
        self.progress_label.pack()

    def create_scheduler_tab(self):
        """Create scheduler tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Scheduler")

        add_frame = ttk.LabelFrame(tab, text="Add Scheduled Task", padding=10)
        add_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(add_frame, text="Task Type:").grid(row=0, column=0, sticky='w', pady=5)
        self.task_type_var = tk.StringVar(value="upload")
        ttk.Combobox(add_frame, textvariable=self.task_type_var,
                     values=["upload", "download", "delete"],
                     state="readonly", width=37).grid(row=0, column=1, padx=5, pady=5, sticky='w')

        ttk.Label(add_frame, text="Source Path:").grid(row=1, column=0, sticky='w', pady=5)
        self.task_source_entry = ttk.Entry(add_frame, width=50)
        self.task_source_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(add_frame, text="Browse",
                   command=lambda: self.browse_file(self.task_source_entry)).grid(row=1, column=2, padx=5)

        ttk.Label(add_frame, text="Dest Path:").grid(row=2, column=0, sticky='w', pady=5)
        self.task_dest_entry = ttk.Entry(add_frame, width=50)
        self.task_dest_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(add_frame, text="Run In (minutes):").grid(row=3, column=0, sticky='w', pady=5)
        self.task_delay_entry = ttk.Entry(add_frame, width=12)
        self.task_delay_entry.insert(0, "5")
        self.task_delay_entry.grid(row=3, column=1, padx=5, pady=5, sticky='w')

        self.recurring_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(add_frame, text="Recurring Task",
                        variable=self.recurring_var).grid(row=4, column=1, sticky='w', pady=5)

        ttk.Label(add_frame, text="Interval (minutes):").grid(row=5, column=0, sticky='w', pady=5)
        self.task_interval_entry = ttk.Entry(add_frame, width=12)
        self.task_interval_entry.insert(0, "60")
        self.task_interval_entry.grid(row=5, column=1, padx=5, pady=5, sticky='w')

        ttk.Button(add_frame, text="Add Task", command=self.add_scheduled_task).grid(row=6, column=1, pady=10)

        list_frame = ttk.LabelFrame(tab, text="Scheduled Tasks", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Bottom rows are packed first so the tree cannot squeeze them out.
        control_frame = ttk.Frame(list_frame)
        control_frame.pack(side='bottom', fill='x', pady=5)
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(side='bottom', fill='x', pady=5)

        columns = ('ID', 'Type', 'Source', 'Destination', 'Next Run', 'Status')
        self.tasks_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        for col in columns:
            self.tasks_tree.heading(col, text=col)
            self.tasks_tree.column(col, width=150)

        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.tasks_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tasks_tree.configure(yscrollcommand=scrollbar.set)
        self.tasks_tree.pack(side='left', fill='both', expand=True)

        ttk.Button(btn_frame, text="Refresh", command=self.refresh_tasks).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_selected_task).pack(side='left', padx=5)

        self.scheduler_btn = ttk.Button(control_frame, text="Start Scheduler", command=self.toggle_scheduler)
        self.scheduler_btn.pack(side='left', padx=5)

        self.scheduler_status_label = ttk.Label(control_frame, text="Scheduler: Stopped")
        self.scheduler_status_label.pack(side='left', padx=5)

    def create_log_tab(self):
        """Create log viewer tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Logs")

        self.log_text = scrolledtext.ScrolledText(tab, wrap=tk.WORD, height=30, state='disabled')
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)

        self.text_handler = TextHandler(self)
        self.text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(self.text_handler)
        if logging.getLogger().level > logging.INFO or logging.getLogger().level == logging.NOTSET:
            logging.getLogger().setLevel(logging.INFO)

    # ----- helpers --------------------------------------------------------

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

    @staticmethod
    def _set_entry(entry: ttk.Entry, value: str) -> None:
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _progress(self, verb: str) -> Callable[[int, int], None]:
        def callback(done: int, total: int) -> None:
            percent = (done / total * 100) if total else 100.0
            self.ui(self.progress_var.set, percent)
            self.ui(self.progress_label.config, {'text': f"{verb}: {done}/{total} bytes ({percent:.1f}%)"})
        return callback

    def _set_connected_state(self, connected: bool, text: str = "Disconnected") -> None:
        self.connect_btn.config(state='disabled' if connected else 'normal')
        self.disconnect_btn.config(state='normal' if connected else 'disabled')
        self.status_bar.config(text=text)

    def _connected_handler(self) -> Optional[SFTPHandler]:
        if self.sftp_handler and self.sftp_handler.is_connected():
            return self.sftp_handler
        messagebox.showerror("Error", "Not connected to server")
        return None

    # ----- actions --------------------------------------------------------

    def load_configuration(self):
        """Load configuration from file"""
        try:
            self.config_manager = ConfigManager(self.config_path)
            conn = self.config_manager.get_connection_details()
        except Exception as e:
            self.config_manager = None
            self.logger.error(f"Failed to load configuration {self.config_path}: {e}")
            return

        self._set_entry(self.host_entry, conn.get('host', ''))
        self._set_entry(self.port_entry, str(conn.get('port', 22)))
        self._set_entry(self.username_entry, conn.get('username', ''))
        self._set_entry(self.password_entry, conn.get('password', ''))
        self._set_entry(self.key_entry, conn.get('private_key_path', ''))
        self._set_entry(self.passphrase_entry, conn.get('private_key_passphrase', ''))

        remote_dir = self.config_manager.get_paths()['remote_upload_dir']
        if remote_dir and not self.upload_remote_entry.get():
            self._set_entry(self.upload_remote_entry, remote_dir.rstrip('/') + '/')

        self.scheduler.check_interval = self.config_manager.get_scheduling_config()['check_interval']
        self.scheduler.set_task_executor(make_task_executor(self.config_manager.get_connection_details))
        self.logger.info(f"Configuration loaded from {self.config_path}")

    def connect(self):
        """Connect to remote server (in the background, so the window stays responsive)"""
        if self.busy:
            messagebox.showwarning("Busy", "Another operation is still running")
            return
        host = self.host_entry.get().strip()
        username = self.username_entry.get().strip()
        try:
            port = int(self.port_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return
        if not host or not username:
            messagebox.showerror("Error", "Host and username are required")
            return

        conn = dict(self.config_manager.get_connection_details()) if self.config_manager else {}
        conn.update({
            'host': host, 'port': port, 'username': username,
            'password': self.password_entry.get(),
            'private_key_path': self.key_entry.get().strip(),
            'private_key_passphrase': self.passphrase_entry.get(),
        })
        handler = SFTPHandler.from_config(conn)
        self.connect_btn.config(state='disabled')
        self.status_bar.config(text=f"Connecting to {host}:{port}...")

        def work():
            if handler.connect():
                self.sftp_handler = handler
                self.ui(self._set_connected_state, True, f"Connected to {host}:{port}")
            else:
                self.ui(self._set_connected_state, False)
                self.ui(messagebox.showerror, "Connection failed", handler.last_error)

        self.run_in_background(work)

    def disconnect(self):
        """Disconnect from server"""
        if self.sftp_handler:
            self.sftp_handler.disconnect()
            self.sftp_handler = None
        self._set_connected_state(False)

    def upload_file(self):
        """Upload file"""
        handler = self._connected_handler()
        if not handler:
            return

        local_path = self.upload_local_entry.get().strip()
        remote_path = self.upload_remote_entry.get().strip()
        if not local_path or not remote_path:
            messagebox.showerror("Error", "Both local and remote paths are required")
            return

        def work():
            if handler.upload_file(local_path, remote_path, self._progress("Uploading")):
                self.ui(messagebox.showinfo, "Success", "File uploaded successfully")
            else:
                self.ui(messagebox.showerror, "Error", "Upload failed (see Logs tab)")

        self.run_in_background(work)

    def download_file(self):
        """Download file"""
        handler = self._connected_handler()
        if not handler:
            return

        remote_path = self.download_remote_entry.get().strip()
        local_path = self.download_local_entry.get().strip()
        if not remote_path or not local_path:
            messagebox.showerror("Error", "Both remote and local paths are required")
            return

        def work():
            if handler.download_file(remote_path, local_path, self._progress("Downloading")):
                self.ui(messagebox.showinfo, "Success", "File downloaded successfully")
            else:
                self.ui(messagebox.showerror, "Error", "Download failed (see Logs tab)")

        self.run_in_background(work)

    def delete_file(self):
        """Delete remote file"""
        handler = self._connected_handler()
        if not handler:
            return

        remote_path = self.delete_remote_entry.get().strip()
        if not remote_path:
            messagebox.showerror("Error", "Remote path is required")
            return

        if not messagebox.askyesno("Confirm delete",
                                   f"Permanently delete this file on the server?\n\n{remote_path}",
                                   icon='warning', default='no'):
            return

        def work():
            if handler.delete_file(remote_path):
                self.ui(messagebox.showinfo, "Success", "File deleted")
            else:
                self.ui(messagebox.showerror, "Error", "Delete failed (see Logs tab)")

        self.run_in_background(work)

    def add_scheduled_task(self):
        """Add a new scheduled task"""
        try:
            task_type = TaskType(self.task_type_var.get())
            delay_minutes = int(self.task_delay_entry.get())
            recurring = self.recurring_var.get()
            interval_minutes = int(self.task_interval_entry.get()) if recurring else 0
            if delay_minutes < 0:
                raise ValueError("Run In must not be negative")

            scheduled_time = datetime.now() + timedelta(minutes=delay_minutes)
            task = ScheduledTask(
                task_id=str(uuid.uuid4()),
                task_type=task_type,
                source_path=self.task_source_entry.get().strip(),
                dest_path=self.task_dest_entry.get().strip(),
                scheduled_time=scheduled_time,
                recurring=recurring,
                interval_minutes=interval_minutes
            )
        except ValueError as e:
            messagebox.showerror("Invalid task", str(e))
            return

        if task_type == TaskType.DELETE and not messagebox.askyesno(
                "Confirm scheduled delete",
                f"This task will delete {task.source_path} on the server"
                f"{' every %d minutes' % interval_minutes if recurring else ''}, unattended.\n\nAdd it?",
                icon='warning', default='no'):
            return

        self.scheduler.add_task(task)
        self.refresh_tasks()
        note = "" if self.scheduler.running else "\n\nThe scheduler is stopped: start it for the task to run."
        messagebox.showinfo("Success", f"Task scheduled for {scheduled_time:%Y-%m-%d %H:%M}.{note}")

    def refresh_tasks(self):
        """Refresh tasks list, keeping the selection"""
        selected = set(self.tasks_tree.selection())
        self.tasks_tree.delete(*self.tasks_tree.get_children())

        for task in self.scheduler.get_all_tasks():
            self.tasks_tree.insert('', 'end', iid=task.task_id, values=(
                task.task_id[:8],
                task.task_type.value,
                task.source_path[-40:],
                task.dest_path[-40:] if task.dest_path else 'N/A',
                f"{task.next_run:%Y-%m-%d %H:%M}" if task.next_run else 'N/A',
                task.describe_status()
            ))
        keep = [iid for iid in selected if self.tasks_tree.exists(iid)]
        if keep:
            self.tasks_tree.selection_set(keep)

        running = self.scheduler.running
        self.scheduler_btn.config(text="Stop Scheduler" if running else "Start Scheduler")
        self.scheduler_status_label.config(text=f"Scheduler: {'Running' if running else 'Stopped'}")

    def remove_selected_task(self):
        """Remove selected tasks"""
        selection = self.tasks_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No task selected")
            return

        for task_id in selection:
            self.scheduler.remove_task(task_id)
        self.refresh_tasks()

    def toggle_scheduler(self):
        """Start/stop scheduler"""
        if self.scheduler.running:
            self.scheduler.stop()
        elif not self.config_manager:
            messagebox.showerror("Error", f"Scheduled tasks need a valid configuration file ({self.config_path})")
        elif not self.config_manager.get_scheduling_config()['enabled']:
            messagebox.showerror("Error", "Scheduling is disabled ([SCHEDULING] enabled = false)")
        else:
            self.scheduler.start()
        self.refresh_tasks()

    def append_log(self, msg: str) -> None:
        """Append a line to the Logs tab (main thread only)"""
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, msg + '\n')
        self.log_text.configure(state='disabled')
        self.log_text.yview(tk.END)

    def on_close(self) -> None:
        """Stop background work and close the window"""
        if self.scheduler.running:
            self.scheduler.stop(timeout=2)
        if self.sftp_handler:
            self.sftp_handler.disconnect()
        logging.getLogger().removeHandler(self.text_handler)
        self.root.destroy()


class TextHandler(logging.Handler):
    """Logging handler that forwards records to the GUI log pane via the UI queue"""

    def __init__(self, app: SFTPPilotGUI):
        super().__init__()
        self.app = app

    def emit(self, record):
        try:
            self.app.ui(self.app.append_log, self.format(record))
        except Exception:
            self.handleError(record)


def run_gui(config_path: str = "config.ini", tasks_file: str = "scheduled_tasks.json"):
    """
    Run the GUI application

    Args:
        config_path: Configuration file to read
        tasks_file: Where scheduled tasks are stored
    """
    root = tk.Tk()
    SFTPPilotGUI(root, config_path, tasks_file)
    root.mainloop()
