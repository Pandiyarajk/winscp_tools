"""
GUI Interface for SFTP Pilot using tkinter

Tk is single-threaded: worker threads never touch a widget. They post
callables to `self._ui_queue`, which the main loop drains every 100 ms.
Colours, fonts and table behaviour live in theme.py; this file is layout and
behaviour.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import logging
import os
import queue
import threading
import tkinter as tk
import uuid
from collections import deque
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional, Tuple

from . import theme
from .config_manager import ConfigManager
from .remote_browser import MODE_ANY, MODE_FILE, MODE_FOLDER, RemoteBrowser, start_folder
from .runner import make_task_executor
from .scheduler import WEEKDAY_NAMES, ScheduledTask, TaskScheduler, TaskStatus, TaskType
from .scrollframe import ScrollFrame
from .sftp_handler import BulkResult, SFTPHandler

UI_POLL_MS = 100
TASKS_REFRESH_MS = 5000
LOG_LINES_KEPT = 5000
SCHEDULE_ONCE = "Once"
SCHEDULE_INTERVAL = "Every N minutes"
SCHEDULE_DAILY = "Daily at a time"
LOG_ALL = "Everything"
LOG_WARNINGS = "Warnings and errors"

TASK_COLUMNS = ('ID', 'Server', 'Type', 'Source', 'Destination', 'Schedule', 'Next Run', 'Status')
# column: (width at 100% DPI, stretches with the window)
TASK_COLUMN_SPECS = {'ID': (76, False), 'Server': (80, False), 'Type': (76, False), 'Source': (220, True),
                     'Destination': (170, True), 'Schedule': (170, False), 'Next Run': (140, False),
                     'Status': (150, False)}
HISTORY_COLUMNS = ('Time', 'Task', 'Server', 'Type', 'Result', 'Try', 'Seconds', 'Runner', 'Error')
HISTORY_COLUMN_SPECS = {'Time': (150, False), 'Task': (84, False), 'Server': (84, False), 'Type': (84, False),
                        'Result': (80, False), 'Try': (50, False), 'Seconds': (80, False), 'Runner': (90, False),
                        'Error': (320, True)}


class SFTPPilotGUI:
    """Main GUI application"""

    def __init__(self, root: tk.Tk, config_path: str = "config.ini",
                 tasks_file: str = "scheduled_tasks.json", prefs_path: Optional[str] = None):
        """
        Initialize GUI

        Args:
            root: Tkinter root window
            config_path: Configuration file to read
            tasks_file: Where scheduled tasks are stored
            prefs_path: Where the theme choice and window size are remembered
                (default: ui_state.json beside the configuration file)
        """
        self.root = root
        self.config_path = config_path
        self.prefs = theme.Prefs(prefs_path or os.path.join(
            os.path.dirname(os.path.abspath(config_path)), "ui_state.json"))
        self.theme_mode = theme.resolve_mode(self.prefs.get("theme", "auto"))
        self.palette = theme.apply_theme(root, self.theme_mode)
        theme.set_window_icon(root)
        self.root.title("SFTP Pilot - File Transfer & Scheduler")
        self.root.geometry(theme.clamp_to_screen(
            root, theme.fit_geometry(root, self.prefs.get("geometry"), "1040x760")))
        self.root.minsize(min(theme.scale(root, 900), root.winfo_screenwidth()),
                          min(theme.scale(root, 620), root.winfo_screenheight() - 90))

        self.config_manager: Optional[ConfigManager] = None
        self.sftp_handler: Optional[SFTPHandler] = None
        self.scheduler = TaskScheduler(tasks_file, runner="gui")
        self.busy = False
        self._closed = False
        self.cancel_event = threading.Event()
        self.logger = logging.getLogger(__name__)
        self._log_lines: List[Tuple[int, str]] = []
        self._log_widget_lines: "deque[int]" = deque()  # text lines per entry shown in the log pane
        self._needs_connection: List[ttk.Button] = []  # disabled until there is a connection

        self._ui_queue: "queue.Queue[Callable[[], object]]" = queue.Queue()

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._drain_job = self.root.after(UI_POLL_MS, self._drain_ui_queue)
        self._refresh_job = self.root.after(TASKS_REFRESH_MS, self._periodic_refresh)

        self.load_configuration()
        self.refresh_tasks()
        self.refresh_history()
        self._set_connected_state(False)

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
            self._drain_job = self.root.after(UI_POLL_MS, self._drain_ui_queue)

    def _periodic_refresh(self) -> None:
        if self._closed:
            return
        self.refresh_tasks()
        self.refresh_history()
        if self.sftp_handler and not self.sftp_handler.is_connected():
            self.logger.warning("Connection lost")
            self.sftp_handler = None
            self._set_connected_state(False)
        self._refresh_job = self.root.after(TASKS_REFRESH_MS, self._periodic_refresh)

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

    def _px(self, pixels: int) -> int:
        """A pixel size scaled for the display's DPI"""
        return theme.scale(self.root, pixels)

    def _finish_operation(self) -> None:
        self.busy = False
        self.progress_var.set(0)
        self.progress_label.config(text="Ready")
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
        # The status bar is packed first so the notebook can never squeeze it out.
        self.status_frame = ttk.Frame(self.root, style="Status.TFrame")
        self.status_frame.pack(side='bottom', fill='x')
        self.theme_btn = ttk.Button(self.status_frame, style="StatusLink.TButton", command=self.toggle_theme,
                                    cursor="hand2")
        self.theme_btn.pack(side='right')
        self.status_summary = ttk.Label(self.status_frame, text="", style="StatusMuted.TLabel")
        self.status_summary.pack(side='right')
        self.status_bar = ttk.Label(self.status_frame, text="Not connected", style="StatusMuted.TLabel")
        self.status_bar.pack(side='left')
        self._create_activity_bar()  # packed next, so it sits right above the status bar

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=self._px(12), pady=(self._px(12), self._px(8)))

        self.create_connection_tab()
        self.create_file_operations_tab()
        self.create_scheduler_tab()
        self.create_history_tab()
        self.create_log_tab()
        self._restyle_widgets()
        self.root.bind("<Control-Key-1>", lambda _e: self.notebook.select(0))
        self.root.bind("<Control-Key-2>", lambda _e: self.notebook.select(1))
        self.root.bind("<Control-Key-3>", lambda _e: self.notebook.select(2))
        self.root.bind("<Control-Key-4>", lambda _e: self.notebook.select(3))
        self.root.bind("<Control-Key-5>", lambda _e: self.notebook.select(4))
        self.root.bind("<F5>", lambda _e: (self.refresh_tasks(), self.refresh_history()))

    def _section(self, parent: tk.Misc, title: str, row: int, pady=(0, 12)) -> ttk.LabelFrame:
        """A titled box whose second column grows with the window"""
        frame = ttk.LabelFrame(parent, text=title, padding=self._px(14))
        frame.grid(row=row, column=0, sticky='ew', pady=pady)
        frame.columnconfigure(1, weight=1)
        return frame

    @staticmethod
    def _buttons(parent: tk.Misc, row: int, column: int,
                 items: List[Tuple[str, Callable[[], None]]]) -> List[ttk.Button]:
        """A row of small buttons in one grid cell; returns them"""
        bar = ttk.Frame(parent)
        bar.grid(row=row, column=column, padx=(10, 0), pady=5, sticky='e')
        made = []
        for index, (text, command) in enumerate(items):
            button = ttk.Button(bar, text=text, command=command)
            button.pack(side='left', padx=(0 if index == 0 else 6, 0))
            made.append(button)
        return made

    @staticmethod
    def _field(parent: tk.Misc, row: int, label: str, show: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label, width=14).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=5)
        entry = ttk.Entry(parent, show=show)
        entry.grid(row=row, column=1, sticky='ew', pady=5)
        return entry

    def create_connection_tab(self):
        """Create connection settings tab"""
        tab = ttk.Frame(self.notebook, padding=self._px(18))
        self.notebook.add(tab, text="Connection")
        tab.columnconfigure(0, weight=1)

        head = ttk.Frame(tab)
        head.grid(row=0, column=0, sticky='ew', pady=(0, 14))
        head.columnconfigure(0, weight=1)
        self.conn_banner = ttk.Label(head, text="\u25cf  Not connected", style="Heading.TLabel")
        self.conn_banner.grid(row=0, column=0, sticky='w')
        ttk.Label(head, text="Server", style="Muted.TLabel").grid(row=0, column=1, padx=(0, 8))
        self.server_var = tk.StringVar()
        self.server_combo = ttk.Combobox(head, textvariable=self.server_var, state="readonly", width=24)
        self.server_combo.grid(row=0, column=2)
        self.server_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_server_fields())

        conn_frame = self._section(tab, "Connection settings (SFTP)", 1)
        self.host_entry = self._field(conn_frame, 0, "Host")
        self.port_entry = self._field(conn_frame, 1, "Port")
        self.port_entry.grid_configure(sticky='w')
        self.port_entry.config(width=8)
        self.username_entry = self._field(conn_frame, 2, "Username")
        self.password_entry = self._field(conn_frame, 3, "Password", show="*")
        self.show_secrets_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(conn_frame, text="Show", variable=self.show_secrets_var,
                        command=self._toggle_secrets).grid(row=3, column=2, padx=(10, 0))
        self.key_entry = self._field(conn_frame, 4, "Private key")
        self._buttons(conn_frame, 4, 2, [("Browse...", lambda: self.browse_file(self.key_entry))])
        self.passphrase_entry = self._field(conn_frame, 5, "Key passphrase", show="*")
        ttk.Label(conn_frame, style="Muted.TLabel",
                  text="Use a private key or a password. With a key file set, the password is not used."
                  ).grid(row=6, column=1, sticky='w', pady=(4, 0))
        for entry in (self.host_entry, self.port_entry, self.username_entry, self.password_entry,
                      self.key_entry, self.passphrase_entry):
            entry.bind("<Return>", lambda _e: self.connect())

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, sticky='w')
        self.connect_btn = ttk.Button(actions, text="Connect", style="Primary.TButton", command=self.connect)
        self.connect_btn.pack(side='left')
        self.disconnect_btn = ttk.Button(actions, text="Disconnect", command=self.disconnect, state='disabled')
        self.disconnect_btn.pack(side='left', padx=8)
        ttk.Button(actions, text="Reload config", command=self.load_configuration).pack(side='left')

        ttk.Label(tab, style="Muted.TLabel", wraplength=theme.scale(self.root, 800), justify='left', text=(
            "Host keys: a new server is remembered on first connect (known_hosts); a server whose key "
            "later changes is refused. With host_key_policy = ask you confirm the fingerprint first. "
            "Scheduled tasks connect with the settings saved in the configuration file, not with the "
            "fields above.")).grid(row=3, column=0, sticky='w', pady=(16, 0))

    def _toggle_secrets(self) -> None:
        shown = "" if self.show_secrets_var.get() else "*"
        self.password_entry.config(show=shown)
        self.passphrase_entry.config(show=shown)

    def create_file_operations_tab(self):
        """Create file operations tab"""
        outer = ttk.Frame(self.notebook, padding=self._px(18))
        self.notebook.add(outer, text="File Operations")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        # Three cards need about 480 px; on a short window this tab scrolls instead of cutting off.
        self.fileops_scroll = ScrollFrame(outer, self.palette["bg"])
        self.fileops_scroll.grid(row=0, column=0, sticky='nsew')
        tab = self.fileops_scroll.body
        tab.columnconfigure(0, weight=1)

        self.fileops_note = ttk.Label(tab, style="Warning.TLabel",
                                      text="Not connected. Connect on the Connection tab first (Ctrl+1).")
        self.fileops_note.grid(row=0, column=0, sticky='w', pady=(0, 10))

        upload = self._section(tab, "Upload", 1)
        self.upload_local_entry = self._field(upload, 0, "Local")
        self._buttons(upload, 0, 2, [("File...", lambda: self.browse_file(self.upload_local_entry)),
                                     ("Folder...", lambda: self.browse_folder(self.upload_local_entry))])
        self.upload_remote_entry = self._field(upload, 1, "Remote")
        self._needs_connection += self._buttons(upload, 1, 2, [("Browse remote...", lambda: self.open_remote_browser(
            self.upload_remote_entry, MODE_FOLDER, add_slash=True, title="Choose the remote folder"))])
        self._hint(upload, "A file, a folder (sent with its contents) or a pattern like D:\\out\\*.csv. "
                           "Remote: end with / for a folder.", 2)
        self.upload_btn = ttk.Button(upload, text="Upload", style="Primary.TButton", command=self.upload_file)
        self.upload_btn.grid(row=2, column=2, sticky='e', padx=(10, 0), pady=(4, 0))
        self._needs_connection.append(self.upload_btn)

        download = self._section(tab, "Download", 2)
        self.download_remote_entry = self._field(download, 0, "Remote")
        self._needs_connection += self._buttons(download, 0, 2, [("Browse remote...", lambda: self.open_remote_browser(
            self.download_remote_entry, MODE_ANY, title="Choose a remote file or folder"))])
        self.download_local_entry = self._field(download, 1, "Save to")
        self._buttons(download, 1, 2, [("Save as...", lambda: self.browse_save_file(self.download_local_entry)),
                                       ("Folder...", lambda: self.browse_folder(self.download_local_entry))])
        self._hint(download, "A file, a folder (fetched with its contents) or a pattern like /in/*.csv. "
                             "A local folder keeps the remote names.", 2)
        self.download_btn = ttk.Button(download, text="Download", style="Primary.TButton",
                                       command=self.download_file)
        self.download_btn.grid(row=2, column=2, sticky='e', padx=(10, 0), pady=(4, 0))
        self._needs_connection.append(self.download_btn)

        delete = self._section(tab, "Delete", 3)
        self.delete_remote_entry = self._field(delete, 0, "Remote file")
        self._needs_connection += self._buttons(delete, 0, 2, [("Browse remote...", lambda: self.open_remote_browser(
            self.delete_remote_entry, MODE_FILE, title="Choose the remote file to delete"))])
        self._hint(delete, "Deletes one file on the server. You are asked to confirm.", 1)
        self.delete_btn = ttk.Button(delete, text="Delete...", style="Danger.TButton", command=self.delete_file)
        self.delete_btn.grid(row=1, column=2, sticky='e', padx=(10, 0), pady=(4, 0))
        self._needs_connection.append(self.delete_btn)

    def _hint(self, parent: tk.Misc, text: str, row: int) -> None:
        """Muted help text under a card's fields; wraps instead of being cut off"""
        ttk.Label(parent, text=text, style="Muted.TLabel", wraplength=self._px(560), justify='left'
                  ).grid(row=row, column=0, columnspan=2, sticky='w', pady=(4, 0))

    def _create_activity_bar(self) -> None:
        """Progress of the running transfer: always in view, whichever tab is open"""
        self.activity_frame = ttk.Frame(self.root)
        self.activity_frame.pack(side='bottom', fill='x', padx=self._px(12), pady=(0, self._px(6)))
        self.activity_frame.columnconfigure(1, weight=1)
        self.progress_label = ttk.Label(self.activity_frame, text="Ready", style="Muted.TLabel",
                                        width=44, anchor='w')
        self.progress_label.grid(row=0, column=0, sticky='w')
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.activity_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=1, sticky='ew', padx=self._px(10))
        self.cancel_btn = ttk.Button(self.activity_frame, text="Cancel", command=self.cancel_transfer,
                                     state='disabled')
        self.cancel_btn.grid(row=0, column=2)

    def create_scheduler_tab(self):
        """Create scheduler tab"""
        tab = ttk.Frame(self.notebook, padding=self._px(18))
        self.notebook.add(tab, text="Scheduler")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        add_frame = ttk.LabelFrame(tab, text="New scheduled task", padding=self._px(14))
        add_frame.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        add_frame.columnconfigure(1, weight=1)

        ttk.Label(add_frame, text="Task", width=14).grid(row=0, column=0, sticky='w', padx=(0, 10), pady=5)
        first = ttk.Frame(add_frame)
        first.grid(row=0, column=1, columnspan=2, sticky='w', pady=5)
        self.task_type_var = tk.StringVar(value="upload")
        ttk.Combobox(first, textvariable=self.task_type_var, values=["upload", "download", "delete"],
                     state="readonly", width=12).pack(side='left')
        ttk.Label(first, text="on server", style="Muted.TLabel").pack(side='left', padx=(18, 8))
        self.task_server_var = tk.StringVar()
        self.task_server_combo = ttk.Combobox(first, textvariable=self.task_server_var, state="readonly", width=22)
        self.task_server_combo.pack(side='left')

        self.task_source_entry = self._field(add_frame, 1, "Source")
        self._buttons(add_frame, 1, 2, [("Browse...", lambda: self.browse_task_path("source")),
                                        ("Folder...", lambda: self.browse_task_path("source", folder=True))])
        self.task_dest_entry = self._field(add_frame, 2, "Destination")
        self._buttons(add_frame, 2, 2, [("Browse...", lambda: self.browse_task_path("dest"))])

        ttk.Label(add_frame, text="Schedule", width=14).grid(row=3, column=0, sticky='nw', padx=(0, 10), pady=7)
        sched_row = ttk.Frame(add_frame)
        sched_row.grid(row=3, column=1, columnspan=2, sticky='w', pady=5)
        self.schedule_kind_var = tk.StringVar(value=SCHEDULE_ONCE)
        schedule_combo = ttk.Combobox(sched_row, textvariable=self.schedule_kind_var, state="readonly", width=18,
                                      values=[SCHEDULE_ONCE, SCHEDULE_INTERVAL, SCHEDULE_DAILY])
        schedule_combo.grid(row=0, column=0, sticky='nw')
        schedule_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_schedule_fields())

        when = ttk.Frame(sched_row)
        when.grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.task_delay_label = ttk.Label(when, text="Start in (minutes)")
        self.task_delay_entry = ttk.Entry(when, width=7)
        self.task_delay_entry.insert(0, "5")
        self.task_interval_label = ttk.Label(when, text="Every (minutes)")
        self.task_interval_entry = ttk.Entry(when, width=7)
        self.task_interval_entry.insert(0, "60")
        self.task_time_label = ttk.Label(when, text="At (HH:MM, 24 h)")
        self.task_time_entry = ttk.Entry(when, width=7)
        self.task_time_entry.insert(0, "02:00")
        self.weekday_frame = ttk.Frame(sched_row)
        self.weekday_vars = []
        for i, name in enumerate(WEEKDAY_NAMES):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(self.weekday_frame, text=name, variable=var).grid(row=0, column=i, padx=(0, 6))
            self.weekday_vars.append(var)
        ttk.Label(self.weekday_frame, text="none ticked = every day", style="Muted.TLabel"
                  ).grid(row=0, column=7, padx=(8, 0))
        self._update_schedule_fields()

        ttk.Label(add_frame, style="Muted.TLabel", wraplength=self._px(600), justify='left', text=(
            "Scheduled tasks connect with the settings in the configuration file, not with the "
            "Connection tab.")).grid(row=4, column=0, columnspan=2, sticky='w', pady=(8, 0))
        ttk.Button(add_frame, text="Add task", style="Primary.TButton", command=self.add_scheduled_task
                   ).grid(row=4, column=2, sticky='e', pady=(8, 0))

        list_frame = ttk.LabelFrame(tab, text="Scheduled tasks", padding=self._px(12))
        list_frame.grid(row=1, column=0, sticky='nsew')
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.tasks_tree = self._table(list_frame, TASK_COLUMNS, TASK_COLUMN_SPECS, height=8)
        self.tasks_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_task_select())
        self.tasks_tree.bind("<Button-3>", self._task_menu)
        self.tasks_tree.bind("<Delete>", lambda _e: self.remove_selected_task())

        bar = ttk.Frame(list_frame)
        bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        ttk.Button(bar, text="Refresh", command=self.refresh_tasks).pack(side='left')
        self.remove_btn = ttk.Button(bar, text="Remove selected", command=self.remove_selected_task, state='disabled')
        self.remove_btn.pack(side='left', padx=8)
        self.history_btn = ttk.Button(bar, text="Show history", command=self.show_task_history, state='disabled')
        self.history_btn.pack(side='left')
        self.scheduler_btn = ttk.Button(bar, text="Start scheduler", style="Primary.TButton",
                                        command=self.toggle_scheduler)
        self.scheduler_btn.pack(side='right')
        self.scheduler_status_label = ttk.Label(bar, text="Scheduler: Stopped", style="Muted.TLabel")
        self.scheduler_status_label.pack(side='right', padx=12)

        self.task_menu = tk.Menu(self.root, tearoff=0)
        self.task_menu.add_command(label="Show history", command=self.show_task_history)
        self.task_menu.add_command(label="Remove", command=self.remove_selected_task)

    def _table(self, parent: tk.Misc, columns: Tuple[str, ...], specs: dict, height: int = 10) -> ttk.Treeview:
        """A sortable table with a vertical scrollbar inside parent's grid cell (0, 0)"""
        holder = ttk.Frame(parent)
        holder.grid(row=0, column=0, columnspan=2, sticky='nsew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        tree = ttk.Treeview(holder, columns=columns, show='headings', height=height)
        for column in columns:
            width, stretch = specs[column]
            tree.heading(column, text=column, anchor='w')
            tree.column(column, width=theme.scale(self.root, width), minwidth=theme.scale(self.root, 44),
                        stretch=stretch, anchor='w')
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        theme.make_sortable(tree, list(columns))
        tree.bind("<Configure>", lambda _e: self._fit_columns(tree, columns, specs))
        return tree

    def _fit_columns(self, tree: ttk.Treeview, columns: Tuple[str, ...], specs: dict) -> None:
        """Share the table's width: fixed columns keep their size, the others split what is left"""
        available = tree.winfo_width()
        flexible = [c for c in columns if specs[c][1]]
        if available < 100 or not flexible:
            return
        fixed = sum(theme.scale(self.root, specs[c][0]) for c in columns if not specs[c][1])
        weight = sum(specs[c][0] for c in flexible)
        room = max(available - fixed, theme.scale(self.root, 70) * len(flexible))
        for column in flexible:
            tree.column(column, width=max(theme.scale(self.root, 70), int(room * specs[column][0] / weight)))

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
            self.task_delay_label.grid(row=0, column=0, sticky='w', padx=(0, 6))
            self.task_delay_entry.grid(row=0, column=1, sticky='w')
        if kind == SCHEDULE_INTERVAL:
            self.task_interval_label.grid(row=0, column=2, sticky='w', padx=(16, 6))
            self.task_interval_entry.grid(row=0, column=3, sticky='w')
        if kind == SCHEDULE_DAILY:
            self.task_time_label.grid(row=0, column=0, sticky='w', padx=(0, 6))
            self.task_time_entry.grid(row=0, column=1, sticky='w')
            self.weekday_frame.grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))

    def create_history_tab(self):
        """Create the run history tab"""
        tab = ttk.Frame(self.notebook, padding=self._px(18))
        self.notebook.add(tab, text="History")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        self.history_selected_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Only the task selected on the Scheduler tab",
                        variable=self.history_selected_only, command=self.refresh_history).pack(side='left')
        ttk.Button(top, text="Refresh", command=self.refresh_history).pack(side='right')

        holder = ttk.Frame(tab)
        holder.grid(row=1, column=0, sticky='nsew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.history_tree = self._table(holder, HISTORY_COLUMNS, HISTORY_COLUMN_SPECS)
        self.history_tree.bind("<Double-1>", lambda _e: self.show_history_details())
        ttk.Label(tab, style="Muted.TLabel", text=(
            "Runs by this window, the console and --run-due (Task Scheduler / cron) all appear here. "
            "Double-click a row for the full message.")).grid(row=2, column=0, sticky='w', pady=(10, 0))

    def refresh_history(self) -> None:
        """Reload the History tab from the shared history file"""
        task_id = ""
        if self.history_selected_only.get():
            selection = self.tasks_tree.selection()
            task_id = selection[0] if selection else "\0"  # nothing selected: show nothing
        self.history_tree.delete(*self.history_tree.get_children())
        for index, record in enumerate(self.scheduler.read_history(task_id, limit=500)):
            result = str(record.get('result', ''))
            self.history_tree.insert('', 'end', tags=("ok" if result == "ok" else "failed",
                                                      "odd" if index % 2 else "even"), values=(
                str(record.get('time', '')).replace('T', ' '),
                str(record.get('task_id', ''))[:8],
                record.get('server', ''),
                record.get('type', ''),
                result,
                record.get('attempt', 1),
                record.get('duration_s', ''),
                record.get('runner', ''),
                record.get('error', ''),
            ))

    def show_history_details(self) -> None:
        """Full text of the selected history row (long errors are clipped in the table)"""
        selection = self.history_tree.selection()
        if not selection:
            return
        values = self.history_tree.item(selection[0])['values']
        lines = [f"{name}: {value}" for name, value in zip(HISTORY_COLUMNS, values)]
        messagebox.showinfo("Run details", "\n".join(lines))

    def show_task_history(self) -> None:
        """Open the History tab filtered to the selected task"""
        if not self.tasks_tree.selection():
            return
        self.history_selected_only.set(True)
        self.refresh_history()
        self.notebook.select(3)

    def create_log_tab(self):
        """Create log viewer tab"""
        tab = ttk.Frame(self.notebook, padding=self._px(18))
        self.notebook.add(tab, text="Logs")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(bar, text="Show", style="Muted.TLabel").pack(side='left', padx=(0, 6))
        self.log_filter_var = tk.StringVar(value=LOG_ALL)
        log_filter = ttk.Combobox(bar, textvariable=self.log_filter_var, state="readonly", width=20,
                                  values=[LOG_ALL, LOG_WARNINGS])
        log_filter.pack(side='left')
        log_filter.bind("<<ComboboxSelected>>", lambda _e: self._render_log())
        self.log_follow_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Follow new lines", variable=self.log_follow_var).pack(side='left', padx=16)
        ttk.Button(bar, text="Save...", command=self.save_log).pack(side='right')
        ttk.Button(bar, text="Copy", command=self.copy_log).pack(side='right', padx=8)
        ttk.Button(bar, text="Clear", command=self.clear_log).pack(side='right')

        holder = ttk.Frame(tab)
        holder.grid(row=1, column=0, sticky='nsew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.log_text = tk.Text(holder, wrap='word', state='disabled', borderwidth=0, relief='flat',
                                highlightthickness=1, padx=10, pady=8, font="TkFixedFont", height=20)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')

        self.text_handler = TextHandler(self)
        self.text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(self.text_handler)
        if logging.getLogger().level > logging.INFO or logging.getLogger().level == logging.NOTSET:
            logging.getLogger().setLevel(logging.INFO)

    # ----- look -----------------------------------------------------------

    def _restyle_widgets(self) -> None:
        """Re-apply colours to the pieces ttk styles do not reach (after a theme change too)"""
        p = self.palette
        self.log_text.configure(background=p["surface"], foreground=p["text"], insertbackground=p["text"],
                                selectbackground=p["selection"], selectforeground=p["selection_text"],
                                highlightbackground=p["border"], highlightcolor=p["accent"])
        self.log_text.tag_configure("DEBUG", foreground=p["muted"])
        self.log_text.tag_configure("INFO", foreground=p["text"])
        self.log_text.tag_configure("WARNING", foreground=p["warning"])
        self.log_text.tag_configure("ERROR", foreground=p["danger"])
        self.log_text.tag_configure("CRITICAL", foreground=p["danger"])
        self.fileops_scroll.restyle(p["bg"])
        for tree in (self.tasks_tree, self.history_tree):
            theme.style_tree_tags(tree, p)
        self.task_menu.configure(background=p["surface"], foreground=p["text"],
                                 activebackground=p["selection"], activeforeground=p["selection_text"])
        self.theme_btn.config(text="Light mode" if self.theme_mode == "dark" else "Dark mode")

    def toggle_theme(self) -> None:
        """Switch between the light and dark look, and remember the choice"""
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.palette = theme.apply_theme(self.root, self.theme_mode)
        self.prefs.set("theme", self.theme_mode)
        self.prefs.save()
        self._restyle_widgets()

    # ----- logs -----------------------------------------------------------

    def _log_visible(self, level: int) -> bool:
        return self.log_filter_var.get() == LOG_ALL or level >= logging.WARNING

    def _write_log_line(self, level: int, msg: str) -> None:
        tag = logging.getLevelName(level) if level in (10, 20, 30, 40, 50) else "INFO"
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, msg + '\n', tag)
        self._log_widget_lines.append(msg.count('\n') + 1)
        while len(self._log_widget_lines) > LOG_LINES_KEPT:  # the pane is capped like the buffer
            self.log_text.delete('1.0', f"{self._log_widget_lines.popleft() + 1}.0")
        self.log_text.configure(state='disabled')
        if self.log_follow_var.get():
            self.log_text.yview(tk.END)

    def _render_log(self) -> None:
        self.log_text.configure(state='normal')
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state='disabled')
        self._log_widget_lines.clear()
        for level, msg in self._log_lines:
            if self._log_visible(level):
                self._write_log_line(level, msg)

    def append_log(self, msg: str, level: int = logging.INFO) -> None:
        """Append a line to the Logs tab (main thread only)"""
        self._log_lines.append((level, msg))
        if len(self._log_lines) > LOG_LINES_KEPT:
            del self._log_lines[:len(self._log_lines) - LOG_LINES_KEPT]
        if self._log_visible(level):
            self._write_log_line(level, msg)

    def clear_log(self) -> None:
        """Empty the log view"""
        self._log_lines.clear()
        self._render_log()

    def copy_log(self) -> None:
        """Copy the visible log lines to the clipboard"""
        text = "\n".join(msg for level, msg in self._log_lines if self._log_visible(level))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def save_log(self) -> None:
        """Save the visible log lines to a file"""
        path = filedialog.asksaveasfilename(defaultextension=".log", initialfile="sftp-pilot.log",
                                            filetypes=[("Log files", "*.log"), ("All files", "*.*")])
        if not path:
            return
        text = "\n".join(msg for level, msg in self._log_lines if self._log_visible(level)) + "\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            messagebox.showerror("Could not save", str(e))

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

    def _set_connected_state(self, connected: bool, text: str = "") -> None:
        """Buttons, the banner on the Connection tab and the status bar"""
        self.connect_btn.config(state='disabled' if connected else 'normal')
        self.disconnect_btn.config(state='normal' if connected else 'disabled')
        for button in self._needs_connection:
            button.config(state='normal' if connected else 'disabled')
        if connected:
            self.fileops_note.grid_remove()
        else:
            self.fileops_note.grid()
        if connected:
            label = text or "Connected"
            self.conn_banner.config(text=f"\u25cf  {label}", style="Success.TLabel")
            self.status_bar.config(text=f"\u25cf {label}", style="StatusSuccess.TLabel")
        else:
            self.conn_banner.config(text="\u25cf  Not connected", style="Heading.TLabel")
            self.status_bar.config(text="\u25cb Not connected", style="StatusMuted.TLabel")

    def _update_summary(self, tasks: List[ScheduledTask]) -> None:
        """Right-hand status bar text: task counts and scheduler state"""
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        parts = [f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"]
        if failed:
            parts.append(f"{failed} failed")
        parts.append("scheduler running" if self.scheduler.running else "scheduler stopped")
        self.status_summary.config(text="   |   ".join(parts),
                                   style="StatusDanger.TLabel" if failed else "StatusMuted.TLabel")

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
        if self.sftp_handler and self.sftp_handler.is_connected():
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
        self.status_bar.config(text=f"\u25cb Connecting to {host}:{port} ...", style="StatusMuted.TLabel")

        def work():
            if handler.connect():
                self.sftp_handler = handler
                self.ui(self._set_connected_state, True, f"Connected to {username}@{host}:{port}")
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

    @staticmethod
    def _status_tag(task: ScheduledTask) -> str:
        """Row colour for a task's state"""
        if task.status == TaskStatus.FAILED:
            return "failed"
        if task.status == TaskStatus.RUNNING:
            return "running"
        if task.status == TaskStatus.PENDING and (task.attempt or task.error_message):
            return "retrying"
        if task.status == TaskStatus.COMPLETED:
            return "ok"
        return "muted" if task.status == TaskStatus.CANCELLED else ""

    def refresh_tasks(self):
        """Refresh tasks list, keeping the selection"""
        selected = set(self.tasks_tree.selection())
        self.tasks_tree.delete(*self.tasks_tree.get_children())

        tasks = self.scheduler.get_all_tasks()
        for index, task in enumerate(tasks):
            tags = [t for t in (self._status_tag(task), "odd" if index % 2 else "even") if t]
            self.tasks_tree.insert('', 'end', iid=task.task_id, tags=tags, values=(
                task.task_id[:8],
                task.server_label,
                task.task_type.value,
                task.source_path,
                task.dest_path if task.dest_path else '',
                task.describe_schedule(),
                f"{task.next_run:%Y-%m-%d %H:%M}" if task.next_run else '',
                task.describe_status()
            ))
        keep = [iid for iid in selected if self.tasks_tree.exists(iid)]
        if keep:
            self.tasks_tree.selection_set(keep)
        self._on_task_select()

        running = self.scheduler.running
        self.scheduler_btn.config(text="Stop scheduler" if running else "Start scheduler")
        self.scheduler_status_label.config(text=f"Scheduler: {'Running' if running else 'Stopped'}")
        self._update_summary(tasks)

    def _on_task_select(self) -> None:
        state = 'normal' if self.tasks_tree.selection() else 'disabled'
        self.remove_btn.config(state=state)
        self.history_btn.config(state=state)

    def _task_menu(self, event) -> None:
        row = self.tasks_tree.identify_row(event.y)
        if not row:
            return
        self.tasks_tree.selection_set(row)
        self.task_menu.tk_popup(event.x_root, event.y_root)

    def remove_selected_task(self):
        """Remove selected tasks"""
        selection = self.tasks_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No task selected")
            return

        count = len(selection)
        if not messagebox.askyesno("Remove task", f"Remove {count} scheduled task{'s' if count != 1 else ''}? "
                                                  f"This cannot be undone.", icon='warning', default='no'):
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

    def _save_prefs(self) -> None:
        """Remember the window size and position (not when the window was never shown)"""
        try:
            if self.root.winfo_viewable():
                self.prefs.set("geometry", self.root.winfo_geometry())
        except tk.TclError:
            return
        self.prefs.save()

    def shutdown(self) -> None:
        """Stop the scheduler, the connection and the UI callbacks; leaves the window alone"""
        self._closed = True
        self._save_prefs()
        for job in (self._drain_job, self._refresh_job):  # nothing should fire at a window that is going away
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        while True:
            try:
                self._ui_queue.get_nowait()
            except queue.Empty:
                break
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
            self.app.ui(self.app.append_log, self.format(record), record.levelno)
        except Exception:
            self.handleError(record)


def run_gui(config_path: str = "config.ini", tasks_file: str = "scheduled_tasks.json"):
    """
    Run the GUI application

    Args:
        config_path: Configuration file to read
        tasks_file: Where scheduled tasks are stored
    """
    theme.enable_dpi_awareness()
    root = tk.Tk()
    SFTPPilotGUI(root, config_path, tasks_file)
    root.mainloop()
