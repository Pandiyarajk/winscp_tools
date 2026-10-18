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
from .remote_browser import MODE_ANY, MODE_FILE, MODE_FOLDER, RemoteBrowser, start_folder
from .scheduler import WEEKDAY_NAMES, ScheduledTask, TaskScheduler, TaskType
from .sftp_handler import BulkResult, SFTPHandler

UI_POLL_MS = 100
TASKS_REFRESH_MS = 5000
SCHEDULE_ONCE = "Once"
SCHEDULE_INTERVAL = "Every N minutes"
SCHEDULE_DAILY = "Daily at a time"


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
        self.scheduler = TaskScheduler(tasks_file, runner="gui")
        self.busy = False
        self._closed = False
        self.cancel_event = threading.Event()
        self.logger = logging.getLogger(__name__)

        self._ui_queue: "queue.Queue[Callable[[], object]]" = queue.Queue()

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(UI_POLL_MS, self._drain_ui_queue)
        self.root.after(TASKS_REFRESH_MS, self._periodic_refresh)

        self.load_configuration()
        self.refresh_tasks()
        self.refresh_history()

    # ----- thread hand-off ------------------------------------------------

    def ui(self, fn: Callable[..., object], *args) -> None:
        """Run fn(*args) on the Tk main thread (safe from any thread)"""
        self._ui_queue.put(lambda: fn(*args))

    def ask_on_ui(self, ask: Callable[[], bool]) -> bool:
        """
        Run a yes/no dialog on the Tk thread and wait for its answer. Called
        from a worker thread; the UI keeps running meanwhile.
        """
        answer: list = []
        done = threading.Event()

        def run() -> None:
            try:
                answer.append(bool(ask()))
            finally:
                done.set()

        self.ui(run)
        done.wait()
        return bool(answer and answer[0])

    def confirm_host_key(self, host: str, key_type: str, fp: str) -> bool:
        """Prompt used by host_key_policy = ask (worker thread safe)"""
        return self.ask_on_ui(lambda: messagebox.askyesno(
            "Unknown server",
            f"First connection to {host}.\n\nKey type: {key_type}\nFingerprint:\n{fp}\n\n"
            f"Compare this with the fingerprint your server administrator gave you "
            f"(or `ssh-keygen -lf` on the server). Trust this server?",
            icon='warning', default='no'))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception as e:
            self.logger.error(f"UI update failed: {e}")
        if not self._closed:
            self.root.after(UI_POLL_MS, self._drain_ui_queue)

    def _periodic_refresh(self) -> None:
        if self._closed:
            return
        self.refresh_tasks()
        self.refresh_history()
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
        self.cancel_btn.config(state='disabled')

    def _start_transfer(self) -> threading.Event:
        """Fresh cancel event for a transfer, with the Cancel button enabled"""
        self.cancel_event = threading.Event()
        self.cancel_btn.config(state='normal')
        return self.cancel_event

    def cancel_transfer(self) -> None:
        """Ask the running transfer to stop; it cleans up its partial file"""
        self.cancel_event.set()
        self.progress_label.config(text="Cancelling...")

    def _item_progress(self, verb: str) -> Callable[[int, int, str], None]:
        """Label update for transfers of many files"""
        def callback(index: int, count: int, name: str) -> None:
            if count > 1:
                self.ui(self.progress_label.config, {'text': f"{verb} {index}/{count}: {name}"})
        return callback

    def _report_transfer(self, result: BulkResult, what: str) -> None:
        """Show the outcome of a transfer (called on a worker thread)"""
        if result.ok:
            self.ui(messagebox.showinfo, "Success", f"{what} completed: {result.summary()}")
        elif result.cancelled:
            self.ui(messagebox.showinfo, "Cancelled",
                    f"{what} cancelled ({result.done} file(s) were already done); "
                    f"nothing was left half-written")
        else:
            self.ui(messagebox.showerror, "Error", f"{what} failed: {result.summary()}")

    # ----- layout ---------------------------------------------------------

    def create_widgets(self):
        """Create GUI widgets"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        self.create_connection_tab()
        self.create_file_operations_tab()
        self.create_scheduler_tab()
        self.create_history_tab()
        self.create_log_tab()

        self.status_bar = tk.Label(self.root, text="Disconnected", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_connection_tab(self):
        """Create connection settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Connection")

        server_frame = ttk.Frame(tab)
        server_frame.pack(fill='x', padx=10, pady=(10, 0))
        ttk.Label(server_frame, text="Server:").pack(side='left')
        self.server_var = tk.StringVar()
        self.server_combo = ttk.Combobox(server_frame, textvariable=self.server_var,
                                         state="readonly", width=30)
        self.server_combo.pack(side='left', padx=6)
        self.server_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_server_fields())
        ttk.Label(server_frame, foreground='gray',
                  text="from the config file: [DEFAULT] and [server:<name>] sections").pack(side='left')

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
        local_buttons = ttk.Frame(upload_frame)
        local_buttons.grid(row=0, column=2, padx=5)
        ttk.Button(local_buttons, text="File...",
                   command=lambda: self.browse_file(self.upload_local_entry)).pack(side='left')
        ttk.Button(local_buttons, text="Folder...",
                   command=lambda: self.browse_folder(self.upload_local_entry)).pack(side='left', padx=(4, 0))

        ttk.Label(upload_frame, text="Remote Path:").grid(row=1, column=0, sticky='w', pady=5)
        self.upload_remote_entry = ttk.Entry(upload_frame, width=60)
        self.upload_remote_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(upload_frame, text="Browse remote...",
                   command=lambda: self.open_remote_browser(
                       self.upload_remote_entry, MODE_FOLDER, add_slash=True,
                       title="Choose the remote folder")).grid(row=1, column=2, padx=5)
        ttk.Label(upload_frame, foreground='gray', text=(
            "Local: a file, a folder (sent with its contents) or a pattern such as D:\\out\\*.csv. "
            "Remote: end with / for a folder.")).grid(row=3, column=0, columnspan=3, sticky='w')

        ttk.Button(upload_frame, text="Upload", command=self.upload_file).grid(row=2, column=1, pady=10)

        download_frame = ttk.LabelFrame(tab, text="Download File", padding=10)
        download_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(download_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.download_remote_entry = ttk.Entry(download_frame, width=60)
        self.download_remote_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(download_frame, text="Browse remote...",
                   command=lambda: self.open_remote_browser(
                       self.download_remote_entry, MODE_ANY,
                       title="Choose a remote file or folder")).grid(row=0, column=2, padx=5)

        ttk.Label(download_frame, text="Local File:").grid(row=1, column=0, sticky='w', pady=5)
        self.download_local_entry = ttk.Entry(download_frame, width=60)
        self.download_local_entry.grid(row=1, column=1, padx=5, pady=5)
        save_buttons = ttk.Frame(download_frame)
        save_buttons.grid(row=1, column=2, padx=5)
        ttk.Button(save_buttons, text="Save as...",
                   command=lambda: self.browse_save_file(self.download_local_entry)).pack(side='left')
        ttk.Button(save_buttons, text="Folder...",
                   command=lambda: self.browse_folder(self.download_local_entry)).pack(side='left', padx=(4, 0))

        ttk.Button(download_frame, text="Download", command=self.download_file).grid(row=2, column=1, pady=10)
        ttk.Label(download_frame, foreground='gray', text=(
            "Remote: a file, a folder (fetched with its contents) or a pattern such as /in/*.csv. "
            "Local: a folder keeps the remote names.")).grid(row=3, column=0, columnspan=3, sticky='w')

        delete_frame = ttk.LabelFrame(tab, text="Delete File", padding=10)
        delete_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(delete_frame, text="Remote Path:").grid(row=0, column=0, sticky='w', pady=5)
        self.delete_remote_entry = ttk.Entry(delete_frame, width=60)
        self.delete_remote_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(delete_frame, text="Browse remote...",
                   command=lambda: self.open_remote_browser(
                       self.delete_remote_entry, MODE_FILE, title="Choose the remote file to delete")
                   ).grid(row=0, column=2, padx=5)

        ttk.Button(delete_frame, text="Delete", command=self.delete_file).grid(row=1, column=1, pady=10)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(tab, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', padx=10, pady=10)

        progress_row = ttk.Frame(tab)
        progress_row.pack(fill='x', padx=10)
        self.cancel_btn = ttk.Button(progress_row, text="Cancel", command=self.cancel_transfer,
                                     state='disabled')
        self.cancel_btn.pack(side='right')
        self.progress_label = ttk.Label(progress_row, text="")
        self.progress_label.pack(side='left')

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
        source_buttons = ttk.Frame(add_frame)
        source_buttons.grid(row=1, column=2, padx=5)
        ttk.Button(source_buttons, text="Browse...",
                   command=lambda: self.browse_task_path("source")).pack(side='left')
        ttk.Button(source_buttons, text="Folder...",
                   command=lambda: self.browse_task_path("source", folder=True)).pack(side='left', padx=(4, 0))

        ttk.Label(add_frame, text="Dest Path:").grid(row=2, column=0, sticky='w', pady=5)
        self.task_dest_entry = ttk.Entry(add_frame, width=50)
        self.task_dest_entry.grid(row=2, column=1, padx=5, pady=5)
        ttk.Button(add_frame, text="Browse...",
                   command=lambda: self.browse_task_path("dest")).grid(row=2, column=2, padx=5)

        ttk.Label(add_frame, text="Schedule:").grid(row=3, column=0, sticky='w', pady=5)
        self.schedule_kind_var = tk.StringVar(value=SCHEDULE_ONCE)
        schedule_combo = ttk.Combobox(add_frame, textvariable=self.schedule_kind_var,
                                      values=[SCHEDULE_ONCE, SCHEDULE_INTERVAL, SCHEDULE_DAILY],
                                      state="readonly", width=37)
        schedule_combo.grid(row=3, column=1, padx=5, pady=5, sticky='w')
        schedule_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_schedule_fields())

        when = ttk.Frame(add_frame)
        when.grid(row=4, column=1, columnspan=2, sticky='w')
        self.task_delay_label = ttk.Label(when, text="Start in (minutes):")
        self.task_delay_entry = ttk.Entry(when, width=8)
        self.task_delay_entry.insert(0, "5")
        self.task_interval_label = ttk.Label(when, text="Every (minutes):")
        self.task_interval_entry = ttk.Entry(when, width=8)
        self.task_interval_entry.insert(0, "60")
        self.task_time_label = ttk.Label(when, text="At (HH:MM, 24 h):")
        self.task_time_entry = ttk.Entry(when, width=8)
        self.task_time_entry.insert(0, "02:00")
        self.weekday_frame = ttk.Frame(when)
        self.weekday_vars = []
        for i, name in enumerate(WEEKDAY_NAMES):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(self.weekday_frame, text=name, variable=var).grid(row=0, column=i)
            self.weekday_vars.append(var)
        ttk.Label(self.weekday_frame, text="(none ticked = every day)").grid(row=0, column=7, padx=5)
        self._update_schedule_fields()

        ttk.Label(add_frame, text="Server:").grid(row=5, column=0, sticky='w', pady=5)
        self.task_server_var = tk.StringVar()
        self.task_server_combo = ttk.Combobox(add_frame, textvariable=self.task_server_var,
                                              state="readonly", width=37)
        self.task_server_combo.grid(row=5, column=1, padx=5, pady=5, sticky='w')

        ttk.Button(add_frame, text="Add Task", command=self.add_scheduled_task).grid(row=6, column=1, pady=10)

        list_frame = ttk.LabelFrame(tab, text="Scheduled Tasks", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Bottom rows are packed first so the tree cannot squeeze them out.
        control_frame = ttk.Frame(list_frame)
        control_frame.pack(side='bottom', fill='x', pady=5)
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(side='bottom', fill='x', pady=5)

        columns = ('ID', 'Server', 'Type', 'Source', 'Destination', 'Schedule', 'Next Run', 'Status')
        self.tasks_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        for col in columns:
            self.tasks_tree.heading(col, text=col)
            self.tasks_tree.column(col, width=130)

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

    def _task_server(self) -> str:
        """Server name stored on a new task ('' means the default server)"""
        name = self.task_server_var.get().strip()
        return "" if name in ("", "default") else name

    def _update_schedule_fields(self) -> None:
        """Show only the inputs the chosen schedule uses"""
        for widget in (self.task_delay_label, self.task_delay_entry, self.task_interval_label,
                       self.task_interval_entry, self.task_time_label, self.task_time_entry,
                       self.weekday_frame):
            widget.grid_forget()
        kind = self.schedule_kind_var.get()
        if kind in (SCHEDULE_ONCE, SCHEDULE_INTERVAL):
            self.task_delay_label.grid(row=0, column=0, sticky='w', padx=5)
            self.task_delay_entry.grid(row=0, column=1, sticky='w')
        if kind == SCHEDULE_INTERVAL:
            self.task_interval_label.grid(row=0, column=2, sticky='w', padx=(15, 5))
            self.task_interval_entry.grid(row=0, column=3, sticky='w')
        if kind == SCHEDULE_DAILY:
            self.task_time_label.grid(row=0, column=0, sticky='w', padx=5)
            self.task_time_entry.grid(row=0, column=1, sticky='w')
            self.weekday_frame.grid(row=1, column=0, columnspan=4, sticky='w', pady=(5, 0))

    def create_history_tab(self):
        """Create the run history tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="History")

        top = ttk.Frame(tab)
        top.pack(fill='x', padx=10, pady=(10, 0))
        self.history_selected_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Only the task selected on the Scheduler tab",
                        variable=self.history_selected_only,
                        command=self.refresh_history).pack(side='left')
        ttk.Button(top, text="Refresh", command=self.refresh_history).pack(side='right')

        columns = ('Time', 'Task', 'Server', 'Type', 'Result', 'Try', 'Seconds', 'Runner', 'Error')
        widths = (140, 80, 70, 70, 60, 40, 70, 70, 400)
        frame = ttk.Frame(tab)
        frame.pack(fill='both', expand=True, padx=10, pady=10)
        self.history_tree = ttk.Treeview(frame, columns=columns, show='headings')
        for col, width in zip(columns, widths):
            self.history_tree.heading(col, text=col)
            self.history_tree.column(col, width=width, stretch=(col == 'Error'))
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.history_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.pack(side='left', fill='both', expand=True)
        ttk.Label(tab, foreground='gray', text=(
            "Runs by the GUI, the console and --run-due (Task Scheduler / cron) all appear here."
        )).pack(fill='x', padx=12, pady=(0, 8))

    def refresh_history(self) -> None:
        """Reload the History tab from the shared history file"""
        task_id = ""
        if self.history_selected_only.get():
            selection = self.tasks_tree.selection()
            task_id = selection[0] if selection else "\0"  # nothing selected: show nothing
        self.history_tree.delete(*self.history_tree.get_children())
        for record in self.scheduler.read_history(task_id, limit=500):
            self.history_tree.insert('', 'end', values=(
                str(record.get('time', '')).replace('T', ' '),
                str(record.get('task_id', ''))[:8],
                record.get('server', ''),
                record.get('type', ''),
                record.get('result', ''),
                record.get('attempt', 1),
                record.get('duration_s', ''),
                record.get('runner', ''),
                record.get('error', ''),
            ))

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

    def browse_folder(self, entry_widget):
        """Browse for a local folder"""
        folder = filedialog.askdirectory()
        if folder:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, folder)

    def open_remote_browser(self, entry_widget, mode: str, add_slash: bool = False,
                            title: str = "Remote files") -> None:
        """
        Pick a remote path in a dialog and put it in an entry

        Args:
            entry_widget: Entry that receives the path
            mode: MODE_FILE, MODE_FOLDER or MODE_ANY
            add_slash: Append '/' to a chosen folder (an upload destination folder)
            title: Dialog title
        """
        handler = self._connected_handler()
        if not handler:
            return
        if self.busy:
            messagebox.showwarning("Busy", "Another operation is still running")
            return
        default = self.config_manager.get_paths()['remote_upload_dir'] if self.config_manager else "/"
        start = start_folder(entry_widget.get(), default)

        def chosen(path: str) -> None:
            if add_slash and not path.endswith('/'):
                path += '/'
            self._set_entry(entry_widget, path)

        RemoteBrowser(self.root, self, handler, start, mode, chosen, title)

    def browse_task_path(self, which: str, folder: bool = False) -> None:
        """
        Browse for a task's source or destination: remote or local depending on the task type

        Args:
            which: 'source' or 'dest'
            folder: Choose a folder rather than a file
        """
        task_type = self.task_type_var.get()
        entry = self.task_source_entry if which == "source" else self.task_dest_entry
        # Upload: source is local, destination is remote. Download and delete: the reverse.
        remote = (task_type != "upload") if which == "source" else (task_type == "upload")
        if remote:
            if which == "dest":
                self.open_remote_browser(entry, MODE_FOLDER, add_slash=True,
                                         title="Choose the remote folder")
            elif task_type == "delete":
                self.open_remote_browser(entry, MODE_FILE, title="Choose the remote file to delete")
            else:
                self.open_remote_browser(entry, MODE_FOLDER if folder else MODE_ANY,
                                         title="Choose a remote file or folder")
        elif folder or which == "dest":
            self.browse_folder(entry)
        else:
            self.browse_file(entry)

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
            names = self.config_manager.server_names()
            if not names:
                raise ValueError("the config describes no server (host and username in "
                                 "[DEFAULT] or in a [server:<name>] section)")
        except Exception as e:
            self.config_manager = None
            self.logger.error(f"Failed to load configuration {self.config_path}: {e}")
            return

        self.server_combo.config(values=names)
        if self.server_var.get() not in names:
            self.server_var.set(names[0])
        self.task_server_combo.config(values=names)
        if self.task_server_var.get() not in names:
            self.task_server_var.set(names[0])
        self.load_server_fields()

        remote_dir = self.config_manager.get_paths()['remote_upload_dir']
        if remote_dir and not self.upload_remote_entry.get():
            self._set_entry(self.upload_remote_entry, remote_dir.rstrip('/') + '/')

        sched_cfg = self.config_manager.get_scheduling_config()
        self.scheduler.check_interval = sched_cfg['check_interval']
        self.scheduler.retries = sched_cfg['retries']
        self.scheduler.retry_delay = sched_cfg['retry_delay']
        self.scheduler.set_task_executor(make_task_executor(self.config_manager.get_connection_details))
        self.logger.info(f"Configuration loaded from {self.config_path}")

    def load_server_fields(self) -> None:
        """Fill the Connection fields from the selected server's config section"""
        if not self.config_manager:
            return
        try:
            conn = self.config_manager.get_connection_details(self.server_var.get())
        except ValueError as e:
            self.logger.error(f"Cannot load server '{self.server_var.get()}': {e}")
            return
        self._set_entry(self.host_entry, conn.get('host', ''))
        self._set_entry(self.port_entry, str(conn.get('port', 22)))
        self._set_entry(self.username_entry, conn.get('username', ''))
        self._set_entry(self.password_entry, conn.get('password', ''))
        self._set_entry(self.key_entry, conn.get('private_key_path', ''))
        self._set_entry(self.passphrase_entry, conn.get('private_key_passphrase', ''))

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

        try:
            conn = (dict(self.config_manager.get_connection_details(self.server_var.get()))
                    if self.config_manager else {})
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return
        conn.update({
            'host': host, 'port': port, 'username': username,
            'password': self.password_entry.get(),
            'private_key_path': self.key_entry.get().strip(),
            'private_key_passphrase': self.passphrase_entry.get(),
        })
        handler = SFTPHandler.from_config(conn, confirm_host_key=self.confirm_host_key)
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

        if self.busy:
            messagebox.showwarning("Busy", "Another operation is still running")
            return
        cancel = self._start_transfer()

        def work():
            result = handler.upload(local_path, remote_path, self._progress("Uploading"), cancel,
                                    self._item_progress("Uploading"))
            self._report_transfer(result, "Upload")

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

        if self.busy:
            messagebox.showwarning("Busy", "Another operation is still running")
            return
        cancel = self._start_transfer()

        def work():
            result = handler.download(remote_path, local_path, self._progress("Downloading"), cancel,
                                      self._item_progress("Downloading"))
            self._report_transfer(result, "Download")

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
            kind = self.schedule_kind_var.get()
            options = {}
            if kind == SCHEDULE_DAILY:
                options['daily_time'] = self.task_time_entry.get().strip()
                options['weekdays'] = [i for i, var in enumerate(self.weekday_vars) if var.get()]
            else:
                delay_minutes = int(self.task_delay_entry.get())
                if delay_minutes < 0:
                    raise ValueError("Start in must not be negative")
                options['scheduled_time'] = datetime.now() + timedelta(minutes=delay_minutes)
                if kind == SCHEDULE_INTERVAL:
                    options['recurring'] = True
                    options['interval_minutes'] = int(self.task_interval_entry.get())
            task = ScheduledTask(
                task_id=str(uuid.uuid4()),
                task_type=task_type,
                source_path=self.task_source_entry.get().strip(),
                dest_path=self.task_dest_entry.get().strip(),
                server=self._task_server(),
                **options,
            )
        except ValueError as e:
            messagebox.showerror("Invalid task", str(e))
            return

        if task_type == TaskType.DELETE and not messagebox.askyesno(
                "Confirm scheduled delete",
                f"This task will delete {task.source_path} on the server, unattended "
                f"({task.describe_schedule()}).\n\nAdd it?",
                icon='warning', default='no'):
            return

        try:
            self.scheduler.add_task(task)
        except (TimeoutError, RuntimeError) as e:
            messagebox.showerror("Could not save task", str(e))
            return
        self.refresh_tasks()
        note = "" if self.scheduler.running else (
            "\n\nThe scheduler in this window is stopped: start it, or let --run-due "
            "(Task Scheduler / cron) run it.")
        when = f"{task.next_run:%Y-%m-%d %H:%M}" if task.next_run else "?"
        messagebox.showinfo("Success", f"Task scheduled ({task.describe_schedule()}), first run {when}.{note}")

    def refresh_tasks(self):
        """Refresh tasks list, keeping the selection"""
        selected = set(self.tasks_tree.selection())
        self.tasks_tree.delete(*self.tasks_tree.get_children())

        for task in self.scheduler.get_all_tasks():
            self.tasks_tree.insert('', 'end', iid=task.task_id, values=(
                task.task_id[:8],
                task.server_label,
                task.task_type.value,
                task.source_path[-40:],
                task.dest_path[-40:] if task.dest_path else 'N/A',
                task.describe_schedule(),
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

    def shutdown(self) -> None:
        """Stop the scheduler, the connection and the UI callbacks; leaves the window alone"""
        self._closed = True
        if self.scheduler.running:
            self.scheduler.stop(timeout=2)
        if self.sftp_handler:
            self.sftp_handler.disconnect()
            self.sftp_handler = None
        logging.getLogger().removeHandler(self.text_handler)

    def on_close(self) -> None:
        """Stop background work and close the window"""
        self.shutdown()
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
