"""
Remote file browser dialog for the GUI.

Listings run on a worker thread and come back through the app's UI queue (Tk
is single-threaded). While a listing runs the app is marked busy, so no
transfer can use the SFTP channel at the same moment.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import posixpath
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any, Callable, List, Optional

from .sftp_handler import RemoteEntry, SFTPHandler, has_wildcard

MODE_FILE = "file"      # pick a file
MODE_FOLDER = "folder"  # pick a folder (the open folder if nothing is selected)
MODE_ANY = "any"        # pick a file or a folder


def human_size(size: int) -> str:
    """
    Format a byte count for a list column

    Args:
        size: Bytes

    Returns:
        For example '812 B', '1.5 MB'
    """
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def start_folder(text: str, default: str = "/") -> str:
    """
    Folder a browser should open at, given what is in the path box

    Args:
        text: Current entry text; may be a file, a folder or a pattern
        default: Used when the text gives nothing usable

    Returns:
        An absolute remote folder
    """
    text = text.strip().replace("\\", "/")
    if not text:
        return default or "/"
    if has_wildcard(text) or not text.endswith("/"):
        text = posixpath.dirname(text) or default
    return text or "/"


class RemoteBrowser(tk.Toplevel):
    """Modal dialog that lists a remote folder and returns the chosen path"""

    def __init__(self, parent: tk.Misc, app: Any, handler: SFTPHandler, start: str, mode: str,
                 on_select: Callable[[str], None], title: str = "Remote files"):
        """
        Args:
            parent: Window the dialog belongs to
            app: The application: needs `ui(fn, *args)` and a boolean `busy`
            handler: A connected handler
            start: Folder to open first
            mode: MODE_FILE, MODE_FOLDER or MODE_ANY
            on_select: Called with the chosen remote path
            title: Window title
        """
        super().__init__(parent)
        self.title(title)
        self.geometry("640x460")
        self.transient(parent)  # type: ignore[arg-type]  # the parent is the app's root window
        self.app = app
        self.handler = handler
        self.mode = mode
        self.on_select = on_select
        self.path = "/"
        self._seq = 0
        self._alive = True
        self._first_load = True
        self._entries: List[RemoteEntry] = []

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(top, text="Up", width=5, command=self.go_up).pack(side="left")
        self.path_var = tk.StringVar(value=start)
        entry = ttk.Entry(top, textvariable=self.path_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self.navigate(self.path_var.get()))
        ttk.Button(top, text="Go", width=5, command=lambda: self.navigate(self.path_var.get())).pack(side="left")
        ttk.Button(top, text="Refresh", command=lambda: self.navigate(self.path)).pack(side="left", padx=(6, 0))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(frame, columns=("name", "size", "modified"), show="headings",
                                 selectmode="browse")
        for col, text, width in (("name", "Name", 340), ("size", "Size", 90), ("modified", "Modified", 140)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="e" if col == "size" else "w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_double_click)

        self.status = ttk.Label(self, text="", foreground="gray")
        self.status.pack(fill="x", padx=10)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=8)
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Select", command=self.select).pack(side="right", padx=6)
        hint = {MODE_FILE: "Select a file", MODE_FOLDER: "Select a folder (or the open one)",
                MODE_ANY: "Select a file or a folder"}[mode]
        ttk.Label(buttons, text=hint, foreground="gray").pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.navigate(start)
        try:
            self.grab_set()
        except tk.TclError:
            pass  # a window that is not viewable yet cannot grab; the dialog still works

    # ----- navigation -------------------------------------------------------

    def close(self) -> None:
        """Close the dialog; a listing still in flight is ignored when it returns"""
        self._alive = False
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def go_up(self) -> None:
        """Open the parent folder"""
        self.navigate(posixpath.dirname(self.path.rstrip("/")) or "/")

    def navigate(self, path: str) -> None:
        """
        List a folder in the background and show it

        Args:
            path: Remote folder
        """
        path = posixpath.normpath(path.strip().replace("\\", "/") or "/")
        if self.app.busy:
            self.status.config(text="Another operation is running; try again when it finishes")
            return
        self.app.busy = True
        self._seq += 1
        seq = self._seq
        self.status.config(text=f"Loading {path} ...")

        def work() -> None:
            try:
                entries = self.handler.list_dir(path)
                self.app.ui(self._show, seq, path, entries)
            except Exception as e:
                self.app.ui(self._show_error, seq, path, str(e) or e.__class__.__name__)
            finally:
                self.app.ui(self._release)

        threading.Thread(target=work, daemon=True).start()

    def _release(self) -> None:
        self.app.busy = False

    def _show(self, seq: int, path: str, entries: List[RemoteEntry]) -> None:
        if not self._alive or seq != self._seq:
            return
        self._first_load = False
        self.path = path
        self._entries = entries
        self.path_var.set(path)
        self.tree.delete(*self.tree.get_children())
        for e in entries:
            modified = datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M") if e.mtime else ""
            label = e.name + ("/" if e.is_dir else "") + ("  (link)" if e.is_link else "")
            self.tree.insert("", "end", iid=e.name, values=(
                label, "" if e.is_dir else human_size(e.size), modified))
        self.status.config(text=f"{len(entries)} item(s) in {path}")

    def _show_error(self, seq: int, path: str, message: str) -> None:
        if not self._alive or seq != self._seq:
            return
        if self._first_load and path != "/":
            self._first_load = False  # the starting folder is gone: fall back to the root once
            self.status.config(text=f"Cannot open {path}: {message}")
            self.app.ui(self.navigate, "/")
            return
        self.status.config(text=f"Cannot open {path}: {message}")

    # ----- choosing ---------------------------------------------------------

    def _selected(self) -> Optional[RemoteEntry]:
        selection = self.tree.selection()
        if not selection:
            return None
        return next((e for e in self._entries if e.name == selection[0]), None)

    def _on_double_click(self, _event: Any = None) -> None:
        entry = self._selected()
        if entry is None:
            return
        if entry.is_dir:
            self.navigate(posixpath.join(self.path, entry.name))
        elif self.mode in (MODE_FILE, MODE_ANY):
            self._choose(posixpath.join(self.path, entry.name))

    def select(self) -> None:
        """Choose the selected item, or the open folder in folder and any mode"""
        entry = self._selected()
        if entry is None:
            if self.mode in (MODE_FOLDER, MODE_ANY):
                self._choose(self.path)
            else:
                messagebox.showinfo("Select a file", "Click a file first.", parent=self)
            return
        full = posixpath.join(self.path, entry.name)
        if entry.is_dir and self.mode == MODE_FILE:
            self.navigate(full)  # a folder cannot be chosen here: open it
        elif not entry.is_dir and self.mode == MODE_FOLDER:
            messagebox.showinfo("Select a folder", "That is a file. Pick a folder.", parent=self)
        else:
            self._choose(full)

    def _choose(self, path: str) -> None:
        self.on_select(path)
        self.close()
