"""
UI behaviour tests for the redesigned GUI: theme, layout, window fitting, the
tasks and history tables, the log pane and the connection tab. They need a
display and tkinter and skip themselves where there is none. Windows are only
ever mapped fully transparent, and are withdrawn again afterwards.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import gc
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

import pytest

tk = pytest.importorskip("tkinter")  # absent on a minimal Linux install: skip the module, do not fail
messagebox = pytest.importorskip("tkinter.messagebox")
filedialog = pytest.importorskip("tkinter.filedialog")
ttk = pytest.importorskip("tkinter.ttk")
pytest.importorskip("asyncssh")

from sftp_server import PASSWORD, USER  # noqa: E402

from sftp_pilot import gui as G  # noqa: E402
from sftp_pilot import theme  # noqa: E402
from sftp_pilot.scheduler import ScheduledTask, TaskStatus, TaskType  # noqa: E402


class DialogLog(list):
    """Records message boxes; askyesno answers with `answer`"""
    answer = True


@pytest.fixture
def dialogs(monkeypatch):
    """Record message boxes instead of showing them"""
    log = DialogLog()
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(messagebox, name, lambda *a, _n=name, **k: log.append((_n, a[:2])))
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda *a, **k: log.append(("askyesno", a[:2])) or log.answer)
    return log


@pytest.fixture(scope="module")
def tk_root():
    """
    One Tk root for the whole module, with garbage collection off so a dead
    root's variables are never finalised on a worker thread (see test_gui.py).
    """
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display available: {e}")
    root.withdraw()
    gc.disable()
    yield root
    try:
        for widget in root.winfo_children():
            widget.destroy()
        root.update()
    finally:
        gc.enable()
        root.destroy()


@pytest.fixture(autouse=True)
def window_stays_hidden(tk_root):
    """Every test must leave the window withdrawn and opaque"""
    yield
    assert tk_root.state() == "withdrawn", "a test left the window visible"
    assert float(tk_root.attributes("-alpha")) == 1.0, "a test left the window transparent"


@pytest.fixture
def config(remote, tmp_path):
    (tmp_path / "remote/in").mkdir(parents=True)
    cfg = tmp_path / "config.ini"
    cfg.write_text(f"[DEFAULT]\nhost = 127.0.0.1\nport = {remote.port}\nusername = {USER}\n"
                   f"password = {PASSWORD}\nknown_hosts_file = kh\ntimeout = 10\n"
                   f"[PATHS]\nremote_upload_dir = /in\n[LOGGING]\nlog_file =\n", encoding="utf-8")
    return cfg


@pytest.fixture
def build(tk_root, config, tmp_path, dialogs, monkeypatch):
    """
    Factory for SFTPPilotGUI on the shared root. Each call shuts the previous
    GUI down and clears the root first; the prefs file and tasks file are the
    same across calls, so a second GUI sees what the first saved.
    """
    monkeypatch.setattr(theme, "system_prefers_dark", lambda: False)
    made = []
    prefs_path = tmp_path / "ui_state.json"

    def clear_root():
        for gui in made:
            gui.shutdown()
        for widget in tk_root.winfo_children():
            widget.destroy()
        tk_root.update()

    def make(prefs=None):
        clear_root()
        if prefs is not None:
            prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
        gui = G.SFTPPilotGUI(tk_root, str(config), str(tmp_path / "tasks.json"), prefs_path=str(prefs_path))
        made.append(gui)
        return gui

    yield make
    try:
        clear_root()
    finally:
        tk_root.update()
        gc.collect()  # on the main thread, while nothing else is running


@pytest.fixture
def app(build):
    return build()


def pump(app, condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end and not condition():
        app.root.update()
        time.sleep(0.02)
    return condition()


def settle(root, rounds=6):
    for _ in range(rounds):
        root.update()
        time.sleep(0.02)


def connect(app):
    app.connect()
    assert pump(app, lambda: app.sftp_handler is not None and not app.busy)


@contextmanager
def mapped(root, geometry):
    """Map the window fully transparent so layout can be measured, then hide it again"""
    root.attributes("-alpha", 0.0)
    try:
        if geometry:
            root.geometry(geometry)
        root.deiconify()
        settle(root)
        yield
    finally:
        root.withdraw()
        root.attributes("-alpha", 1.0)
        root.update()


def need_screen(root, width, height):
    if root.winfo_screenwidth() < width + 30 or root.winfo_screenheight() < height + 30:
        pytest.skip(f"screen {root.winfo_screenwidth()}x{root.winfo_screenheight()} is too small "
                    f"for a {width}x{height} window")


def big_size(root):
    """1300x800, or the largest size below it that fits this screen"""
    width, height = min(1300, root.winfo_screenwidth() - 30), min(800, root.winfo_screenheight() - 30)
    if width < 1000 or height < 680:
        pytest.skip("screen too small for a window larger than 900x640")
    return width, height


def find_widgets(parent, widget_class, text=None):
    found = []
    for child in parent.winfo_children():
        if child.winfo_class() == widget_class:
            try:
                if text is None or str(child.cget("text")) == text:
                    found.append(child)
            except tk.TclError:
                pass
        found.extend(find_widgets(child, widget_class, text))
    return found


def state_of(widget):
    return str(widget.cget("state"))


def color(value):
    return str(value).lower()


def make_task(app, name, status=TaskStatus.PENDING, server="", **attrs):
    task = ScheduledTask(task_id=f"{name}-0000-task", task_type=TaskType.DELETE,
                         source_path=f"/in/{name}.txt", server=server)
    task.status = status
    for key, value in attrs.items():
        setattr(task, key, value)
    app.scheduler.add_task(task)
    return task


def history(app, task_id, result="ok", error="", server="default"):
    app.scheduler._append_history({
        "time": datetime.now().replace(microsecond=0).isoformat(), "task_id": task_id, "server": server,
        "type": "delete", "result": result, "attempt": 1, "duration_s": 0.5, "runner": "gui", "error": error})


def tree_rows(tree):
    return [tree.item(i) for i in tree.get_children()]


# ----- 1. theme -----------------------------------------------------------


def test_toggle_theme_flips_palette_styles_and_widgets(app, tk_root):
    style = ttk.Style(tk_root)
    first = app.theme_mode
    assert first == "light"  # system_prefers_dark is patched to False
    for expected in ("dark", "light", "dark"):
        app.toggle_theme()
        settle(tk_root, 2)
        p = theme.PALETTES[expected]
        assert app.theme_mode == expected and app.palette is p
        assert color(style.lookup("Primary.TButton", "background")) == p["accent"]
        assert color(style.lookup("Status.TFrame", "background")) == p["surface2"]
        assert str(app.theme_btn.cget("text")) == ("Light mode" if expected == "dark" else "Dark mode")
        assert color(app.log_text.cget("background")) == p["surface"]
        assert color(app.log_text.cget("foreground")) == p["text"]
        for tree in (app.tasks_tree, app.history_tree):
            assert color(tree.tag_configure("failed", "foreground")) == p["danger"]
            assert color(tree.tag_configure("ok", "foreground")) == p["success"]
            assert color(tree.tag_configure("odd", "background")) == p["surface2"]
        assert color(app.log_text.tag_cget("ERROR", "foreground")) == p["danger"]


def test_theme_choice_is_saved_and_restored_by_a_new_window(build, tk_root, tmp_path):
    app = build({})
    app.toggle_theme()
    assert app.theme_mode == "dark"
    saved = json.loads(open(app.prefs.path, encoding="utf-8").read())
    assert saved["theme"] == "dark"

    again = build()  # same prefs file, system still says light
    assert again.theme_mode == "dark"
    assert color(again.log_text.cget("background")) == theme.PALETTES["dark"]["surface"]
    assert str(again.theme_btn.cget("text")) == "Light mode"
    assert color(ttk.Style(tk_root).lookup("Primary.TButton", "background")) == theme.PALETTES["dark"]["accent"]

    again.toggle_theme()
    third = build()
    assert third.theme_mode == "light"
    assert json.loads(open(third.prefs.path, encoding="utf-8").read())["theme"] == "light"


def test_saved_dark_wins_over_system_light_and_auto_follows_system(build, monkeypatch):
    monkeypatch.setattr(theme, "system_prefers_dark", lambda: False)
    assert build({"theme": "dark"}).theme_mode == "dark"
    monkeypatch.setattr(theme, "system_prefers_dark", lambda: True)
    assert build({"theme": "light"}).theme_mode == "light"
    assert build({"theme": "auto"}).theme_mode == "dark"
    assert build({}).theme_mode == "dark"
    monkeypatch.setattr(theme, "system_prefers_dark", lambda: False)
    assert build({"theme": "nonsense"}).theme_mode == "light"


# ----- 2. layout ----------------------------------------------------------


def tree_columns_fit(tree):
    widths = [int(tree.column(c, "width")) for c in tree["columns"]]
    return sum(widths), tree.winfo_width(), widths


def test_status_bar_is_inside_the_window_on_every_tab(app, tk_root):
    need_screen(tk_root, 1000, 700)
    with mapped(tk_root, "1000x700+20+20"):
        for index in range(5):
            app.notebook.select(index)
            settle(tk_root, 3)
            bottom = app.status_frame.winfo_rooty() + app.status_frame.winfo_height()
            window_bottom = tk_root.winfo_rooty() + tk_root.winfo_height()
            assert app.status_frame.winfo_height() >= 16, f"status bar squeezed on tab {index}"
            assert bottom <= window_bottom, f"status bar pushed out of the window on tab {index}"
            assert app.status_frame.winfo_ismapped()
            assert app.status_frame.winfo_width() >= tk_root.winfo_width() - 2


@pytest.mark.parametrize("size", ["1000x700", "900x640", "big"])
def test_task_table_shows_every_column_at_any_size(app, tk_root, size):
    if size == "big":
        width, height = big_size(tk_root)
        size = "%dx%d" % (width, height)
    else:
        width, height = (int(v) for v in size.split("x"))
        need_screen(tk_root, width, height)
    with mapped(tk_root, "1000x700+10+10"):
        app.notebook.select(2)
        settle(tk_root)
        tk_root.geometry(f"{width}x{height}+10+10")
        settle(tk_root)
        tree = app.tasks_tree
        total, available, widths = tree_columns_fit(tree)
        assert min(widths) >= 40, widths
        assert total <= available + 2, f"Status column cut off at {size}: columns {total}px, table {available}px"
        bottom = app.status_frame.winfo_rooty() + app.status_frame.winfo_height()
        assert bottom <= tk_root.winfo_rooty() + tk_root.winfo_height()


def test_flexible_task_columns_follow_the_window(app, tk_root):
    big = "%dx%d" % big_size(tk_root)
    with mapped(tk_root, "900x640+10+10"):
        app.notebook.select(2)
        settle(tk_root)
        small = {c: int(app.tasks_tree.column(c, "width")) for c in app.tasks_tree["columns"]}
        tk_root.geometry(big + "+10+10")
        settle(tk_root)
        big = {c: int(app.tasks_tree.column(c, "width")) for c in app.tasks_tree["columns"]}
        assert big["Source"] > small["Source"]
        assert big["Destination"] > small["Destination"]
        for name in ("ID", "Server", "Type", "Schedule", "Next Run", "Status"):
            assert big[name] == small[name], f"fixed column {name} changed width"
        assert min(big.values()) >= 40


def test_history_table_fits_and_error_column_grows(app, tk_root):
    big = "%dx%d" % big_size(tk_root)
    with mapped(tk_root, "900x640+10+10"):
        app.notebook.select(3)
        settle(tk_root)
        small = int(app.history_tree.column("Error", "width"))
        total, available, _ = tree_columns_fit(app.history_tree)
        assert total <= available + 2, f"history columns {total}px, table {available}px at 900x640"
        tk_root.geometry(big + "+10+10")
        settle(tk_root)
        assert int(app.history_tree.column("Error", "width")) > small


def test_connection_entries_grow_with_the_window(app, tk_root):
    big = "%dx%d" % big_size(tk_root)
    with mapped(tk_root, "900x640+10+10"):
        app.notebook.select(0)
        settle(tk_root)
        narrow = app.host_entry.winfo_width()
        tk_root.geometry(big + "+10+10")
        settle(tk_root)
        wide = app.host_entry.winfo_width()
        assert wide > narrow
        assert app.password_entry.winfo_width() == wide


# ----- 3. clamp_to_screen --------------------------------------------------


def parse(geometry):
    size, _, rest = geometry.partition("+")
    w, h = (int(v) for v in size.split("x"))
    x, y = (int(v) for v in rest.split("+"))
    return w, h, x, y


def assert_fits(root, geometry, margin=72):
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h, x, y = parse(geometry)
    assert x >= 0 and y >= 0, geometry
    assert x + w <= sw, geometry
    assert y + h <= sh - margin, geometry


def test_clamp_cuts_a_geometry_larger_than_the_screen(tk_root):
    sw, sh = tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
    result = theme.clamp_to_screen(tk_root, f"{sw + 800}x{sh + 800}+0+0")
    w, h, x, y = parse(result)
    assert w == sw and h == max(sh - 72, 200)
    assert_fits(tk_root, result)
    custom = theme.clamp_to_screen(tk_root, f"{sw + 5}x{sh + 5}+0+0", bottom_margin=150)
    assert parse(custom)[1] == max(sh - 150, 200)
    assert_fits(tk_root, custom, margin=150)


def test_clamp_moves_a_window_that_hangs_off_the_bottom_up(tk_root):
    sh = tk_root.winfo_screenheight()
    if sh < 500:
        pytest.skip("screen too small")
    result = theme.clamp_to_screen(tk_root, f"600x400+50+{sh - 100}")
    w, h, x, y = parse(result)
    assert (w, h, x) == (600, 400, 50)
    assert y == sh - 72 - 400
    assert_fits(tk_root, result)
    exact = theme.clamp_to_screen(tk_root, f"600x400+50+{sh - 72 - 400}")
    assert parse(exact)[3] == sh - 72 - 400  # already fits: left alone


def test_clamp_moves_negative_and_far_right_positions_in(tk_root):
    sw = tk_root.winfo_screenwidth()
    assert theme.clamp_to_screen(tk_root, "800x600+-50+-30") == "800x600+0+0"
    assert theme.clamp_to_screen(tk_root, "800x600+-8+-8") == "800x600+0+0"
    result = theme.clamp_to_screen(tk_root, f"800x600+{sw + 500}+10")
    assert parse(result)[2] == sw - 800
    assert_fits(tk_root, result)


def test_clamp_centres_a_bare_size_near_the_top(tk_root):
    sw, sh = tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
    result = theme.clamp_to_screen(tk_root, "1040x760")
    w, h, x, y = parse(result)
    assert w == min(1040, sw) and h == min(760, max(sh - 72, 200))
    assert x == (sw - w) // 2
    assert 0 <= y <= 24
    assert_fits(tk_root, result)


@pytest.mark.parametrize("garbage", ["", "garbage", "100x", "x100", "1040X760+1+1", "800x600+5", "800x600-5-5",
                                     "800x600+a+b", "-800x600"])
def test_clamp_returns_garbage_unchanged(tk_root, garbage):
    assert theme.clamp_to_screen(tk_root, garbage) == garbage


def test_clamp_result_always_fits(tk_root):
    sw, sh = tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
    if sh < 400:
        pytest.skip("screen too small")
    sizes = [(1, 1), (300, 200), (900, 620), (sw, sh), (sw + 1, sh + 1), (99999, 99999)]
    positions = [None, (0, 0), (-9999, -9999), (sw, sh), (99999, 99999), (sw // 2, sh // 2), (-8, 10)]
    for w, h in sizes:
        for pos in positions:
            geometry = f"{w}x{h}" if pos is None else f"{w}x{h}+{pos[0]}+{pos[1]}"
            result = theme.clamp_to_screen(tk_root, geometry)
            if h < 200:
                continue  # a tiny height is kept as asked; only the screen limits matter
            assert_fits(tk_root, result)


@pytest.mark.parametrize("saved", ["5000x4000+9000+9000", "1000x700+9000+9000", "1000x700+-500+-500",
                                   "1000x700+0+99999"])
def test_gui_with_an_absurd_saved_geometry_fits_the_screen(build, tk_root, saved):
    app = build({"geometry": saved})
    sw, sh = tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
    with mapped(tk_root, None):  # the geometry the GUI set for itself
        settle(tk_root)
        w, h, x, y = parse(tk_root.geometry())
        assert x >= 0 and y >= 0
        assert x + w <= sw
        assert y + h <= sh - 72 or h <= app.root.winfo_reqheight()
        bottom = app.status_frame.winfo_rooty() + app.status_frame.winfo_height()
        assert bottom <= tk_root.winfo_rooty() + tk_root.winfo_height()


# ----- 4. tasks table -------------------------------------------------------


def test_task_rows_get_the_right_colour_tag(app):
    now = datetime.now().isoformat()
    me = {"host": app.scheduler._host, "pid": os.getpid(), "token": "another-instance", "run": "r1", "at": now}
    tasks = {
        "failed": make_task(app, "failed", TaskStatus.FAILED, error_message="boom"),
        "running": make_task(app, "running", TaskStatus.RUNNING, claim=me),
        "retry": make_task(app, "retry", TaskStatus.PENDING, attempt=2),
        "pending-err": make_task(app, "pending-err", TaskStatus.PENDING, error_message="last run failed"),
        "ok": make_task(app, "ok", TaskStatus.COMPLETED),
        "muted": make_task(app, "muted", TaskStatus.CANCELLED),
        "plain": make_task(app, "plain", TaskStatus.PENDING),
    }
    expected = {"failed": "failed", "running": "running", "retry": "retrying", "pending-err": "retrying",
                "ok": "ok", "muted": "muted", "plain": None}
    app.refresh_tasks()
    assert len(app.tasks_tree.get_children()) == len(tasks)
    for name, task in tasks.items():
        tags = set(app.tasks_tree.item(task.task_id, "tags"))
        zebra = tags & {"even", "odd"}
        assert len(zebra) == 1, f"{name}: zebra tags {tags}"
        status_tags = tags - zebra
        assert status_tags == ({expected[name]} if expected[name] else set()), f"{name}: {tags}"
    assert app.tasks_tree.item(tasks["retry"].task_id, "values")[7] == "retrying (2 failed)"


def test_zebra_stripes_alternate(app):
    for name in ("one", "two", "three", "four"):
        make_task(app, name)
    app.refresh_tasks()
    zebra = [next(iter(set(app.tasks_tree.item(i, "tags")) & {"even", "odd"})) for i in app.tasks_tree.get_children()]
    assert zebra == ["even", "odd", "even", "odd"]


def test_row_buttons_follow_the_selection_and_remove_works(app, tk_root):
    keep = make_task(app, "keep")
    gone = make_task(app, "gone")
    app.refresh_tasks()
    assert state_of(app.remove_btn) == "disabled" and state_of(app.history_btn) == "disabled"

    app.tasks_tree.selection_set(gone.task_id)
    tk_root.update()
    assert state_of(app.remove_btn) == "normal" and state_of(app.history_btn) == "normal"

    app.tasks_tree.selection_remove(gone.task_id)
    tk_root.update()
    assert state_of(app.remove_btn) == "disabled"

    app.tasks_tree.selection_set(gone.task_id)
    tk_root.update()
    app.remove_selected_task()
    assert list(app.tasks_tree.get_children()) == [keep.task_id]
    assert [t.task_id for t in app.scheduler.get_all_tasks()] == [keep.task_id]
    assert state_of(app.remove_btn) == "disabled", "buttons stay enabled for a row that is gone"


def test_remove_with_nothing_selected_warns(app, dialogs):
    make_task(app, "keep")
    app.refresh_tasks()
    app.remove_selected_task()
    assert dialogs[-1][0] == "showwarning"
    assert len(app.scheduler.get_all_tasks()) == 1


def test_show_task_history_opens_history_filtered_to_the_task(app, tk_root):
    alpha = make_task(app, "alpha")
    beta = make_task(app, "beta")
    history(app, alpha.task_id, "ok")
    history(app, beta.task_id, "failed", error="nope")
    history(app, alpha.task_id, "failed", error="again")
    app.refresh_tasks()
    app.refresh_history()
    assert len(app.history_tree.get_children()) == 3

    app.show_task_history()  # nothing selected: no change
    assert not app.history_selected_only.get() and app.notebook.index(app.notebook.select()) == 0

    app.tasks_tree.selection_set(alpha.task_id)
    tk_root.update()
    app.show_task_history()
    assert app.notebook.index(app.notebook.select()) == 3
    assert app.history_selected_only.get() is True
    rows = tree_rows(app.history_tree)
    assert len(rows) == 2
    assert {r["values"][1] for r in rows} == {alpha.task_id[:8]}

    app.tasks_tree.selection_set(beta.task_id)
    tk_root.update()
    app.refresh_history()
    assert [r["values"][1] for r in tree_rows(app.history_tree)] == [beta.task_id[:8]]

    app.tasks_tree.selection_remove(beta.task_id)
    tk_root.update()
    app.refresh_history()
    assert app.history_tree.get_children() == (), "ticked box with no selection shows nothing"
    app.history_selected_only.set(False)
    app.refresh_history()
    assert len(app.history_tree.get_children()) == 3


def test_server_heading_sorts_the_table_and_restripes(app):
    make_task(app, "t1", server="zeta")
    make_task(app, "t2", server="alpha")
    make_task(app, "t3", server="")
    app.refresh_tasks()
    tree = app.tasks_tree

    def servers():
        return [tree.item(i, "values")[1] for i in tree.get_children()]

    command = tree.heading("Server", "command")
    tree.tk.call(command)
    assert servers() == ["alpha", "default", "zeta"]
    assert tree.heading("Server", "text").endswith("▲")
    zebra = [next(iter(set(tree.item(i, "tags")) & {"even", "odd"})) for i in tree.get_children()]
    assert zebra == ["even", "odd", "even"]
    tree.tk.call(command)
    assert servers() == ["zeta", "default", "alpha"]
    assert tree.heading("Server", "text").endswith("▼")
    assert tree.heading("Type", "text") == "Type"


def test_status_summary_counts_tasks_and_failures(app):
    assert "0 tasks" in str(app.status_summary.cget("text"))
    make_task(app, "one")
    app.refresh_tasks()
    text = str(app.status_summary.cget("text"))
    assert "1 task" in text and "1 tasks" not in text and "failed" not in text
    make_task(app, "two", TaskStatus.FAILED, error_message="x")
    app.refresh_tasks()
    text = str(app.status_summary.cget("text"))
    assert "2 tasks" in text and "1 failed" in text and "scheduler stopped" in text


def test_scheduler_toggle_updates_summary_button_and_label(app):
    make_task(app, "done", TaskStatus.COMPLETED)  # never due: the scheduler has nothing to run
    app.refresh_tasks()
    assert "scheduler stopped" in str(app.status_summary.cget("text"))
    try:
        app.toggle_scheduler()
        assert app.scheduler.running
        assert "scheduler running" in str(app.status_summary.cget("text"))
        assert str(app.scheduler_btn.cget("text")) == "Stop scheduler"
        assert "Running" in str(app.scheduler_status_label.cget("text"))
        app.toggle_scheduler()
        assert not app.scheduler.running
        assert "scheduler stopped" in str(app.status_summary.cget("text"))
        assert str(app.scheduler_btn.cget("text")) == "Start scheduler"
        assert "Stopped" in str(app.scheduler_status_label.cget("text"))
    finally:
        if app.scheduler.running:
            app.scheduler.stop(timeout=5)


def test_scheduler_refuses_to_start_when_disabled(app, dialogs, config):
    config.write_text(config.read_text(encoding="utf-8") + "[SCHEDULING]\nenabled = false\n", encoding="utf-8")
    app.load_configuration()
    try:
        app.toggle_scheduler()
        assert not app.scheduler.running
        assert dialogs[-1][0] == "showerror"
    finally:
        if app.scheduler.running:
            app.scheduler.stop(timeout=5)


# ----- 5. history tab -------------------------------------------------------


def test_history_rows_are_tagged_by_result(app):
    task = make_task(app, "h")
    history(app, task.task_id, "ok")
    history(app, task.task_id, "failed", error="bad")
    history(app, task.task_id, "ok")
    app.refresh_history()
    rows = tree_rows(app.history_tree)
    assert len(rows) == 3
    for row in rows:
        result = row["values"][4]
        tags = set(row["tags"])
        assert (result == "ok" and "ok" in tags and "failed" not in tags) or \
               (result == "failed" and "failed" in tags and "ok" not in tags)
        assert len(tags & {"even", "odd"}) == 1
    assert sorted(r["values"][4] for r in rows) == ["failed", "ok", "ok"]


def test_history_details_show_the_full_long_error(app, dialogs, tk_root):
    task = make_task(app, "h")
    long_error = "E" * 300
    history(app, task.task_id, "failed", error=long_error)
    app.refresh_history()
    app.show_history_details()  # nothing selected: no box
    assert not dialogs
    app.history_tree.selection_set(app.history_tree.get_children()[0])
    tk_root.update()
    app.show_history_details()
    kind, (title, message) = dialogs[-1]
    assert kind == "showinfo" and title == "Run details"
    assert long_error in message
    assert "Result: failed" in message and "Server: default" in message


# ----- 6. logs tab -------------------------------------------------------------


def log_lines(app):
    text = app.log_text.get("1.0", "end-1c")
    if text.endswith("\n"):
        text = text[:-1]  # the newline that ends the last line
    return text.split("\n") if text else []


def test_log_levels_get_matching_tags(app):
    app.clear_log()
    for level, name in ((logging.DEBUG, "DEBUG"), (logging.INFO, "INFO"), (logging.WARNING, "WARNING"),
                        (logging.ERROR, "ERROR"), (logging.CRITICAL, "CRITICAL")):
        app.append_log(f"{name.lower()} line", level)
    assert log_lines(app) == ["debug line", "info line", "warning line", "error line", "critical line"]
    for number, name in enumerate(("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), start=1):
        tags = app.log_text.tag_names(f"{number}.0")
        assert name in tags, f"line {number} lacks tag {name}: {tags}"
        assert not ({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} - {name}) & set(tags)
    app.append_log("odd level", 25)
    assert "INFO" in app.log_text.tag_names("6.0")
    p = app.palette
    assert color(app.log_text.tag_cget("WARNING", "foreground")) == p["warning"]


def test_log_filter_hides_info_and_restores_in_order(app):
    app.clear_log()
    app.append_log("d1", logging.DEBUG)
    app.append_log("i1", logging.INFO)
    app.append_log("w1", logging.WARNING)
    app.append_log("i2", logging.INFO)
    app.append_log("e1", logging.ERROR)
    app.log_filter_var.set(G.LOG_WARNINGS)
    app._render_log()
    assert log_lines(app) == ["w1", "e1"]
    app.append_log("i3", logging.INFO)  # hidden while filtered
    app.append_log("w2", logging.WARNING)
    assert log_lines(app) == ["w1", "e1", "w2"]
    assert "WARNING" in app.log_text.tag_names("1.0") and "ERROR" in app.log_text.tag_names("2.0")
    app.log_filter_var.set(G.LOG_ALL)
    app._render_log()
    assert log_lines(app) == ["d1", "i1", "w1", "i2", "e1", "i3", "w2"]


def test_log_buffer_is_capped(app, monkeypatch):
    monkeypatch.setattr(G, "LOG_LINES_KEPT", 50)
    app.clear_log()
    for n in range(80):
        app.append_log(f"line {n}")
    assert [m for _l, m in app._log_lines] == [f"line {n}" for n in range(30, 80)]
    app._render_log()
    assert log_lines(app) == [f"line {n}" for n in range(30, 80)]


def test_log_widget_is_capped_like_the_buffer(app, monkeypatch):
    monkeypatch.setattr(G, "LOG_LINES_KEPT", 50)
    app.clear_log()
    for n in range(80):
        app.append_log(f"line {n}")
    assert len(log_lines(app)) == 50
    assert log_lines(app) == [f"line {n}" for n in range(30, 80)]  # the oldest went, not the newest
    app.append_log("multi\nline entry")  # an entry of two text lines counts once and trims whole entries
    assert len(app._log_lines) == 50 and log_lines(app)[-2:] == ["multi", "line entry"]
    # 49 one-line entries plus the two-line one: the cap counts entries, not text lines
    assert app.log_text.get("1.0", "end-1c").count("\n") == 51


def test_clear_log_empties_buffer_and_widget(app):
    app.append_log("x", logging.WARNING)
    app.clear_log()
    assert app._log_lines == [] and app.log_text.get("1.0", "end-1c") == "" and log_lines(app) == []
    assert state_of(app.log_text) == "disabled"


def test_copy_log_puts_exactly_the_visible_lines_on_the_clipboard(app, tk_root):
    app.clear_log()
    for text, level in (("i1", logging.INFO), ("w1", logging.WARNING), ("e1", logging.ERROR)):
        app.append_log(text, level)
    app.copy_log()
    assert tk_root.clipboard_get() == "i1\nw1\ne1"
    app.log_filter_var.set(G.LOG_WARNINGS)
    app._render_log()
    app.copy_log()
    assert tk_root.clipboard_get() == "w1\ne1" == "\n".join(log_lines(app))


def test_save_log_writes_visible_lines_and_reports_a_bad_path(app, dialogs, monkeypatch, tmp_path):
    app.clear_log()
    for text, level in (("i1", logging.INFO), ("w1", logging.WARNING)):
        app.append_log(text, level)
    target = tmp_path / "out.log"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: str(target))
    app.save_log()
    assert target.read_text(encoding="utf-8") == "i1\nw1\n"

    app.log_filter_var.set(G.LOG_WARNINGS)
    app._render_log()
    app.save_log()
    assert target.read_text(encoding="utf-8") == "w1\n"

    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: str(tmp_path / "no-such-dir" / "x.log"))
    app.save_log()  # must not raise
    assert dialogs[-1][0] == "showerror" and dialogs[-1][1][0] == "Could not save"

    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: "")
    before = len(dialogs)
    app.save_log()  # cancelled: nothing happens
    assert len(dialogs) == before


def test_real_logging_calls_reach_the_log_pane(app):
    app.clear_log()
    logging.getLogger("x").warning("boom %s", "now")
    assert pump(app, lambda: any("boom now" in line for line in log_lines(app)))
    index = next(i for i, line in enumerate(log_lines(app), start=1) if "boom now" in line)
    assert "WARNING" in app.log_text.tag_names(f"{index}.0")
    assert "- WARNING - boom now" in log_lines(app)[index - 1]


# ----- 7. connection tab -----------------------------------------------------------


def test_connection_state_banner_status_bar_and_buttons(app, remote):
    def initial():
        assert "Not connected" in str(app.conn_banner.cget("text"))
        assert "Not connected" in str(app.status_bar.cget("text"))
        assert state_of(app.disconnect_btn) == "disabled"
        assert state_of(app.connect_btn) == "normal"

    initial()
    connect(app)
    who = f"{USER}@127.0.0.1:{remote.port}"
    assert who in str(app.conn_banner.cget("text"))
    assert who in str(app.status_bar.cget("text"))
    assert "Not connected" not in str(app.conn_banner.cget("text"))
    assert state_of(app.connect_btn) == "disabled" and state_of(app.disconnect_btn) == "normal"
    assert str(app.conn_banner.cget("style")) == "Success.TLabel"

    app.disconnect()
    initial()
    assert str(app.conn_banner.cget("style")) == "Heading.TLabel"


def test_failed_connection_returns_to_the_initial_state(app, dialogs, tk_root):
    app._set_entry(app.port_entry, "1")  # nothing listens there
    app.connect()
    assert pump(app, lambda: not app.busy)
    assert pump(app, lambda: any(d[0] == "showerror" for d in dialogs))
    assert "Not connected" in str(app.status_bar.cget("text"))
    assert state_of(app.connect_btn) == "normal" and state_of(app.disconnect_btn) == "disabled"


def test_show_checkbutton_toggles_both_secret_masks(app, tk_root):
    box = find_widgets(app.notebook, "TCheckbutton", "Show")
    assert len(box) == 1
    assert str(app.password_entry.cget("show")) == "*" and str(app.passphrase_entry.cget("show")) == "*"
    box[0].invoke()
    assert str(app.password_entry.cget("show")) == "" and str(app.passphrase_entry.cget("show")) == ""
    assert str(app.host_entry.cget("show")) == ""
    box[0].invoke()
    assert str(app.password_entry.cget("show")) == "*" and str(app.passphrase_entry.cget("show")) == "*"


def test_return_key_is_bound_on_every_field(app):
    for entry in (app.host_entry, app.port_entry, app.username_entry, app.password_entry, app.key_entry,
                  app.passphrase_entry):
        assert entry.bind("<Return>"), "no Return binding"


def test_return_in_a_field_connects_when_disconnected(app, tk_root):
    need_screen(tk_root, 1000, 700)
    with mapped(tk_root, "1000x700+20+20"):
        app.notebook.select(0)
        settle(tk_root)
        app.password_entry.focus_force()
        settle(tk_root, 3)
        app.password_entry.event_generate("<Return>")
        assert pump(app, lambda: app.sftp_handler is not None and not app.busy, seconds=15), \
            "Return did not start a connection"
    assert state_of(app.disconnect_btn) == "normal"
    # Return while connected does nothing and does not raise
    app.password_entry.event_generate("<Return>")
    tk_root.update()
    assert app.sftp_handler is not None


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_control_digit_selects_the_tab(app, tk_root, number):
    assert tk_root.bind(f"<Control-Key-{number}>"), "shortcut not bound"
    need_screen(tk_root, 1000, 700)
    with mapped(tk_root, "1000x700+20+20"):
        app.notebook.select(0 if number != 1 else 4)
        settle(tk_root)
        tk_root.focus_force()
        settle(tk_root, 3)
        tk_root.event_generate(f"<Control-Key-{number}>")
        settle(tk_root, 3)
        assert app.notebook.index(app.notebook.select()) == number - 1


# ----- 8. cleanliness ----------------------------------------------------------------


def test_no_threads_or_windows_are_left_behind(build, tk_root):
    baseline = threading.active_count()
    app = build()
    connect(app)
    app.toggle_scheduler()
    assert app.scheduler.running
    app.toggle_scheduler()
    app.disconnect()
    app.shutdown()
    assert pump(app, lambda: threading.active_count() <= baseline, seconds=10), \
        [t.name for t in threading.enumerate()]
    for widget in tk_root.winfo_children():
        widget.destroy()
    tk_root.update()
    assert tk_root.winfo_children() == []
    assert not [h for h in logging.getLogger().handlers if isinstance(h, G.TextHandler)]
    assert tk_root.state() == "withdrawn"
