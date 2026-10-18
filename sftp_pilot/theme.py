"""
Look and feel for the GUI: light and dark palettes on ttk's `clam` theme,
fonts, a Windows dark title bar, saved window preferences, and sortable
tables. Kept apart from gui.py so that file only describes layout.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import json
import os
import re
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Dict, List, Optional

MODES = ("light", "dark")

PALETTES: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#eceef2", "border": "#cdd2da", "border_strong": "#9aa3b2",
        "text": "#1b1f24", "muted": "#667085", "accent": "#2563eb", "accent_hover": "#1d4ed8",
        "accent_text": "#ffffff", "danger": "#b42318", "success": "#15803d", "warning": "#b45309",
        "info": "#1d4ed8", "selection": "#dbe7fd", "selection_text": "#0f172a",
    },
    "dark": {
        "bg": "#1c1e22", "surface": "#272a30", "surface2": "#2f333a", "border": "#434852", "border_strong": "#6b7383",
        "text": "#e7e9ee", "muted": "#9aa3b2", "accent": "#4c8dff", "accent_hover": "#6ba0ff",
        "accent_text": "#0b1220", "danger": "#ff7b72", "success": "#56d364", "warning": "#e3b341",
        "info": "#79b8ff", "selection": "#27406b", "selection_text": "#ffffff",
    },
}

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def system_prefers_dark() -> bool:
    """
    Whether the operating system is set to dark mode

    Returns:
        True on Windows with "Choose your default app mode" set to Dark; False
        elsewhere or when it cannot be read
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        with key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def resolve_mode(preference: str) -> str:
    """
    Turn a saved preference into 'light' or 'dark'

    Args:
        preference: 'light', 'dark' or 'auto' (follow the system)
    """
    if preference in MODES:
        return preference
    return "dark" if system_prefers_dark() else "light"


class Prefs:
    """Small JSON file next to the config: theme choice and window geometry"""

    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        """Write the file; a failure (read-only folder) is ignored, preferences are a convenience"""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except OSError:
            pass


def scale(root: tk.Misc, pixels: int) -> int:
    """
    Scale a pixel size for the display's DPI (100% = 96 dpi)

    Args:
        root: Any widget
        pixels: Size at 100%
    """
    try:
        return max(1, round(pixels * root.winfo_fpixels("1i") / 96.0))
    except tk.TclError:
        return pixels


def _configure_fonts(root: tk.Misc) -> Dict[str, str]:
    families = set(tkfont.families(root))
    if sys.platform == "win32":
        base = "Segoe UI" if "Segoe UI" in families else tkfont.nametofont("TkDefaultFont").actual("family")
        mono = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"
        size = 10
    elif sys.platform == "darwin":
        base, mono, size = "Helvetica Neue", "Menlo", 12
    else:
        base = "DejaVu Sans" if "DejaVu Sans" in families else tkfont.nametofont("TkDefaultFont").actual("family")
        mono, size = ("DejaVu Sans Mono" if "DejaVu Sans Mono" in families else "TkFixedFont"), 10
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        tkfont.nametofont(name).configure(family=base, size=size)
    tkfont.nametofont("TkFixedFont").configure(family=mono, size=size)
    return {"base": base, "mono": mono, "size": str(size)}


def apply_theme(root: tk.Tk, mode: str) -> Dict[str, str]:
    """
    Style every ttk widget class and the plain tk defaults for light or dark

    Args:
        root: The application window
        mode: 'light' or 'dark'

    Returns:
        The palette in use
    """
    p = PALETTES[mode if mode in MODES else "light"]
    fonts = _configure_fonts(root)
    base, size = fonts["base"], int(fonts["size"])
    style = ttk.Style(root)
    style.theme_use("clam")
    pad = scale(root, 6)

    root.configure(background=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["surface"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"],
                    troughcolor=p["surface2"], focuscolor=p["accent"], selectbackground=p["selection"],
                    selectforeground=p["selection_text"], insertcolor=p["text"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("Heading.TLabel", background=p["bg"], foreground=p["text"], font=(base, size + 2, "bold"))
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["text"], font=(base, size, "bold"))

    strong = p["border_strong"]
    style.configure("TButton", background=p["surface"], foreground=p["text"], bordercolor=strong,
                    lightcolor=strong, darkcolor=strong, padding=(scale(root, 14), pad), relief="flat",
                    borderwidth=1, focusthickness=1)
    style.map("TButton", background=[("disabled", p["bg"]), ("pressed", p["surface2"]), ("active", p["surface2"])],
              foreground=[("disabled", p["muted"])],
              bordercolor=[("disabled", p["border"]), ("focus", p["accent"])],
              lightcolor=[("disabled", p["border"])], darkcolor=[("disabled", p["border"])])
    style.configure("Primary.TButton", background=p["accent"], foreground=p["accent_text"], bordercolor=p["accent"],
                    lightcolor=p["accent"], darkcolor=p["accent"], font=(base, size, "bold"))
    style.map("Primary.TButton", background=[("disabled", p["bg"]), ("pressed", p["accent_hover"]),
                                             ("active", p["accent_hover"])],
              foreground=[("disabled", p["muted"])], font=[("disabled", (base, size))],
              bordercolor=[("disabled", p["border"])], lightcolor=[("disabled", p["border"])],
              darkcolor=[("disabled", p["border"])])
    style.configure("Danger.TButton", background=p["surface"], foreground=p["danger"], bordercolor=p["danger"],
                    lightcolor=p["danger"], darkcolor=p["danger"])
    style.map("Danger.TButton", background=[("disabled", p["bg"]), ("active", p["surface2"])],
              foreground=[("disabled", p["muted"])], bordercolor=[("disabled", p["border"])],
              lightcolor=[("disabled", p["border"])], darkcolor=[("disabled", p["border"])])
    style.configure("Link.TButton", background=p["bg"], foreground=p["accent"], borderwidth=0, padding=(pad, 2))
    style.map("Link.TButton", foreground=[("active", p["accent_hover"])], background=[("active", p["bg"])])
    style.configure("StatusLink.TButton", background=p["surface2"], foreground=p["accent"], borderwidth=0,
                    padding=(pad, 2))
    style.map("StatusLink.TButton", foreground=[("active", p["accent_hover"])],
              background=[("active", p["surface2"])])

    for entry in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(entry, fieldbackground=p["surface"], foreground=p["text"], bordercolor=strong,
                        lightcolor=strong, darkcolor=strong, padding=scale(root, 5), insertcolor=p["text"],
                        arrowcolor=p["muted"], background=p["surface2"])
        style.map(entry, bordercolor=[("focus", p["accent"])], fieldbackground=[("disabled", p["surface2"])],
                  foreground=[("disabled", p["muted"])])
    style.map("TCombobox", fieldbackground=[("readonly", p["surface"])], foreground=[("readonly", p["text"])],
              selectbackground=[("readonly", p["surface"])], selectforeground=[("readonly", p["text"])])

    for check in ("TCheckbutton", "TRadiobutton"):
        style.configure(check, background=p["bg"], foreground=p["text"], indicatorbackground=p["surface"],
                        indicatorforeground=p["accent"], bordercolor=p["border"])
        style.map(check, background=[("active", p["bg"])], indicatorbackground=[("selected", p["surface"])])

    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(0, 0, 0, 0))
    tab_padding = (scale(root, 18), scale(root, 8))
    style.configure("TNotebook.Tab", background=p["surface2"], foreground=p["muted"], bordercolor=p["border"],
                    padding=tab_padding, font=(base, size))
    # clam maps a smaller padding onto the selected tab, which made the strip change width
    style.map("TNotebook.Tab", background=[("selected", p["bg"]), ("active", p["surface"])],
              foreground=[("selected", p["accent"]), ("active", p["text"])],
              padding=[("selected", tab_padding)], expand=[("selected", (0, 0, 0, 0))])

    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                    bordercolor=p["border"], rowheight=scale(root, 26), borderwidth=1)
    style.map("Treeview", background=[("selected", p["selection"])], foreground=[("selected", p["selection_text"])])
    style.configure("Treeview.Heading", background=p["surface2"], foreground=p["text"], relief="flat",
                    padding=(scale(root, 4), scale(root, 6)), font=(base, size, "bold"), bordercolor=p["border"])
    style.map("Treeview.Heading", background=[("active", p["border"])])

    style.configure("Vertical.TScrollbar", background=p["surface2"], troughcolor=p["bg"], arrowcolor=p["muted"],
                    bordercolor=p["bg"], gripcount=0)
    style.configure("Horizontal.TScrollbar", background=p["surface2"], troughcolor=p["bg"], arrowcolor=p["muted"],
                    bordercolor=p["bg"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", p["border"])])
    style.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["surface2"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"],
                    thickness=scale(root, 10))
    style.configure("TSeparator", background=p["border"])

    style.configure("Status.TFrame", background=p["surface2"])
    style.configure("Status.TLabel", background=p["surface2"], foreground=p["text"], padding=(scale(root, 8), 3))
    style.configure("StatusMuted.TLabel", background=p["surface2"], foreground=p["muted"], padding=(scale(root, 8), 3))
    for tone in ("success", "danger", "warning", "info"):
        style.configure(f"{tone.capitalize()}.TLabel", background=p["bg"], foreground=p[tone], font=(base, size, "bold"))
        style.configure(f"Status{tone.capitalize()}.TLabel", background=p["surface2"], foreground=p[tone],
                        font=(base, size, "bold"), padding=(scale(root, 8), 3))

    # Plain tk pieces that ttk styles do not reach: drop-down lists, dialogs, menus.
    root.option_add("*TCombobox*Listbox.background", p["surface"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["selection"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["selection_text"])
    root.option_add("*TCombobox*Listbox.font", (base, size))
    root.option_add("*Toplevel.background", p["bg"])
    root.option_add("*Menu.background", p["surface"])
    root.option_add("*Menu.foreground", p["text"])
    root.option_add("*Menu.activeBackground", p["selection"])
    root.option_add("*Menu.activeForeground", p["selection_text"])
    root.option_add("*Menu.borderWidth", 0)
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel):
            child.configure(background=p["bg"])
            set_dark_titlebar(child, mode == "dark")
    set_dark_titlebar(root, mode == "dark")
    return p


def set_dark_titlebar(window: tk.Misc, dark: bool) -> None:
    """Ask Windows 10/11 for a dark (or light) title bar; silently does nothing elsewhere"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE on Windows 11 / early Windows 10
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def set_window_icon(root: tk.Tk) -> None:
    """Use the bundled icon for the window and the taskbar, if the files are there"""
    png = os.path.join(ASSETS, "icon.png")
    try:
        if os.path.exists(png):
            image = tk.PhotoImage(master=root, file=png)
            root.iconphoto(True, image)
            root._sftp_pilot_icon = image  # type: ignore[attr-defined]  # Tk drops it if unreferenced
        ico = os.path.join(ASSETS, "icon.ico")
        if sys.platform == "win32" and os.path.exists(ico):
            root.iconbitmap(ico)
    except tk.TclError:
        pass


def enable_dpi_awareness() -> None:
    """Render crisply on high-DPI Windows displays; call before the first Tk window"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def style_tree_tags(tree: ttk.Treeview, palette: Dict[str, str]) -> None:
    """Row colours for status words and zebra striping"""
    tree.tag_configure("even", background=palette["surface"])
    tree.tag_configure("odd", background=palette["surface2"])
    tree.tag_configure("ok", foreground=palette["success"])
    tree.tag_configure("failed", foreground=palette["danger"])
    tree.tag_configure("running", foreground=palette["info"])
    tree.tag_configure("retrying", foreground=palette["warning"])
    tree.tag_configure("muted", foreground=palette["muted"])


def _sort_key(value: str) -> Any:
    text = str(value)
    try:
        return (0, float(text.split()[0]))
    except (ValueError, IndexError):
        return (1, text.lower())


def make_sortable(tree: ttk.Treeview, columns: List[str]) -> None:
    """
    Sort a table by clicking a column heading (again to reverse)

    Args:
        tree: The table
        columns: Its column names
    """
    state = {"column": None, "reverse": False}
    titles = {c: tree.heading(c, "text") for c in columns}

    def sort_by(column: str) -> None:
        reverse = state["column"] == column and not state["reverse"]
        rows = [(tree.set(item, column), item) for item in tree.get_children("")]
        rows.sort(key=lambda r: _sort_key(r[0]), reverse=reverse)
        for index, (_value, item) in enumerate(rows):
            tree.move(item, "", index)
            tags = [t for t in tree.item(item, "tags") if t not in ("even", "odd")]
            tree.item(item, tags=tags + ["odd" if index % 2 else "even"])
        state["column"], state["reverse"] = column, reverse
        for name in columns:
            arrow = ""
            if name == column:
                arrow = "  ▼" if reverse else "  ▲"
            tree.heading(name, text=titles[name] + arrow)

    for column in columns:
        tree.heading(column, command=lambda c=column: sort_by(c))


def clamp_to_screen(root: tk.Misc, geometry: str, bottom_margin: int = 72) -> str:
    """
    Make a window geometry fit on the screen with its title bar and status bar in view

    The size is cut down to the screen (minus room for the taskbar), and the position is
    moved so the whole window is visible. A geometry without a position is centred
    horizontally and placed near the top.

    Args:
        root: Any widget, used for the screen size
        geometry: 'WxH' or 'WxH+X+Y' (a '+-8' style negative position is accepted)
        bottom_margin: Pixels to keep free at the bottom for the taskbar

    Returns:
        A geometry string 'WxH+X+Y' that fits; the input unchanged if it cannot be parsed
    """
    match = re.fullmatch(r"(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?", geometry.strip())
    if not match:
        return geometry
    width, height = int(match.group(1)), int(match.group(2))
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    width = min(width, screen_w)
    height = min(height, max(screen_h - bottom_margin, 200))
    if match.group(3) is None:
        x, y = (screen_w - width) // 2, 24
    else:
        x, y = int(match.group(3)), int(match.group(4))
    x = min(max(x, 0), max(screen_w - width, 0))
    y = min(max(y, 0), max(screen_h - bottom_margin - height, 0))
    return f"{width}x{height}+{x}+{y}"


def fit_geometry(root: tk.Tk, saved: Optional[str], default: str) -> str:
    """
    A saved window geometry, if it still fits on a screen; otherwise the default

    Args:
        root: The application window
        saved: A Tk geometry string such as '1000x720+40+30', or None
        default: Size to use when nothing usable was saved
    """
    if not saved:
        return default
    try:
        size, _, pos = saved.partition("+")
        width, height = (int(v) for v in size.split("x"))
        x, y = (int(v) for v in pos.split("+")) if pos else (0, 0)
    except ValueError:
        return default
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    if width < 600 or height < 400 or width > screen_w or height > screen_h:
        return default
    x = min(max(x, 0), max(screen_w - 120, 0))
    y = min(max(y, 0), max(screen_h - 120, 0))
    return f"{width}x{height}+{x}+{y}"
