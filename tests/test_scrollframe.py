"""
ScrollFrame: scrolls only when the window is too short for its content.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import gc
import time

import pytest

tk = pytest.importorskip("tkinter")
ttk = pytest.importorskip("tkinter.ttk")

from sftp_pilot import theme  # noqa: E402
from sftp_pilot.scrollframe import ScrollFrame  # noqa: E402


@pytest.fixture(scope="module")
def root():
    try:
        window = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display available: {e}")
    window.withdraw()
    theme.apply_theme(window, "light")
    gc.disable()
    yield window
    gc.enable()
    window.destroy()


def settle(root, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def build(root, rows, size):
    """A transparent mapped window holding a ScrollFrame with `rows` 30px-high labels"""
    top = tk.Toplevel(root)
    top.attributes("-alpha", 0.0)
    top.geometry(size)
    frame = ScrollFrame(top, "#f3f4f6")
    frame.pack(fill="both", expand=True)
    for n in range(rows):
        ttk.Label(frame.body, text=f"row {n}").pack(fill="x", ipady=8)
    settle(root)
    return top, frame


def test_short_window_scrolls_and_reaches_the_bottom(root):
    top, frame = build(root, rows=40, size="400x300+0+0")
    try:
        assert frame.needs_scrolling and frame.scrollbar.winfo_ismapped()
        region = [int(float(v)) for v in frame.canvas.cget("scrollregion").split()]
        assert region[3] >= frame.body.winfo_reqheight() > frame.canvas.winfo_height()
        assert frame.canvas.yview()[0] == 0.0
        frame._wheel(1)
        root.update()
        assert frame.canvas.yview()[0] > 0.0, "the wheel did not scroll"
        frame.canvas.yview_moveto(1.0)
        root.update()
        assert frame.canvas.yview()[1] == pytest.approx(1.0)  # the last row is reachable
        for _ in range(60):
            frame._wheel(-1)
        root.update()
        assert frame.canvas.yview()[0] == 0.0
    finally:
        top.destroy()


def test_tall_window_has_no_scrollbar_and_ignores_the_wheel(root):
    top, frame = build(root, rows=2, size="400x500+0+0")
    try:
        assert not frame.needs_scrolling and not frame.scrollbar.winfo_ismapped()
        frame._wheel(1)
        root.update()
        assert frame.canvas.yview()[0] == 0.0
    finally:
        top.destroy()


def test_growing_the_window_removes_the_scrollbar(root):
    top, frame = build(root, rows=14, size="400x200+0+0")
    try:
        assert frame.needs_scrolling
        frame.canvas.yview_moveto(0.5)
        top.geometry("400x700+0+0")
        settle(root)
        assert not frame.needs_scrolling and not frame.scrollbar.winfo_ismapped()
        assert frame.canvas.yview()[0] == 0.0, "left scrolled although everything fits"
        top.geometry("400x200+0+0")
        settle(root)
        assert frame.needs_scrolling and frame.scrollbar.winfo_ismapped()
    finally:
        top.destroy()


def test_body_follows_the_window_width(root):
    top, frame = build(root, rows=3, size="400x400+0+0")
    try:
        narrow = frame.body.winfo_width()
        top.geometry("700x400+0+0")
        settle(root)
        assert frame.body.winfo_width() > narrow + 200
    finally:
        top.destroy()


def test_restyle_changes_the_canvas_colour(root):
    top, frame = build(root, rows=1, size="300x200+0+0")
    try:
        frame.restyle("#1c1e22")
        assert frame.canvas.cget("background") == "#1c1e22"
    finally:
        top.destroy()


def test_the_wheel_is_only_bound_while_the_pointer_is_over_the_frame(root):
    top, frame = build(root, rows=40, size="400x300+0+0")
    try:
        frame._release_wheel()
        before = frame.bind_all("<MouseWheel>")
        frame._grab_wheel()
        assert frame.bind_all("<MouseWheel>") != before or frame.bind_all("<Button-4>")
        frame._release_wheel()
        assert not frame.bind_all("<MouseWheel>") and not frame.bind_all("<Button-4>")
    finally:
        top.destroy()
