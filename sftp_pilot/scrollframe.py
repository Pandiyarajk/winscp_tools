"""
A frame whose content scrolls vertically when the window is too short for it.

The scrollbar only appears when needed, the content follows the window width,
and the mouse wheel scrolls while the pointer is over the frame.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import sys
import tkinter as tk
from tkinter import ttk
from typing import Any


class ScrollFrame(ttk.Frame):
    """Put widgets in `.body`; it scrolls if it is taller than the space it gets"""

    def __init__(self, parent: tk.Misc, background: str):
        """
        Args:
            parent: Containing widget
            background: Canvas colour (the theme's page background)
        """
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=background)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.needs_scrolling = False
        self.body.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._sync)
        self.bind("<Enter>", self._grab_wheel)
        self.bind("<Leave>", self._release_wheel)

    def restyle(self, background: str) -> None:
        """Follow a theme change"""
        self.canvas.configure(background=background)

    def _sync(self, _event: Any = None) -> None:
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        needed = self.body.winfo_reqheight()
        if width > 1:
            self.canvas.itemconfigure(self._window, width=width)
        self.canvas.configure(scrollregion=(0, 0, width, max(needed, height)))
        self.needs_scrolling = needed > height > 1
        if self.needs_scrolling:
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)

    def _grab_wheel(self, _event: Any = None) -> None:
        if sys.platform.startswith("linux"):
            self.bind_all("<Button-4>", lambda _e: self._wheel(-1))
            self.bind_all("<Button-5>", lambda _e: self._wheel(1))
        else:
            self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _release_wheel(self, _event: Any = None) -> None:
        for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.unbind_all(sequence)

    def _on_mousewheel(self, event: Any) -> None:
        step = -1 if event.delta > 0 else 1
        if sys.platform == "darwin":
            step = -event.delta
        self._wheel(step)

    def _wheel(self, step: int) -> None:
        if self.needs_scrolling:
            self.canvas.yview_scroll(step * 3, "units")
