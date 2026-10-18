"""
GUI tests against a real SFTP server. They need a display and tkinter, and
skip themselves where there is none (a headless Linux box).

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import gc
import time
from tkinter import messagebox

import pytest

tk = pytest.importorskip("tkinter")
pytest.importorskip("asyncssh")

from sftp_server import PASSWORD, USER  # noqa: E402

from sftp_pilot import gui as G  # noqa: E402
from sftp_pilot.remote_browser import MODE_ANY, MODE_FILE, MODE_FOLDER, human_size, start_folder  # noqa: E402


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
    One Tk root for the whole module. Creating and destroying roots test after
    test lets the garbage collector finalise a dead root's variables on a worker
    thread, which makes a Tk call off the main thread and hangs without a
    mainloop (the app itself runs a real mainloop). Collection stays off during
    the module and is done by hand on the main thread between tests.
    """
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    gc.disable()
    yield root
    gc.enable()
    root.destroy()


@pytest.fixture
def app(tk_root, remote, tmp_path, dialogs):
    (tmp_path / "remote/in/2026").mkdir(parents=True)
    (tmp_path / "remote/in/a.csv").write_text("a")
    (tmp_path / "remote/in/b.csv").write_text("bb")
    (tmp_path / "remote/readme.txt").write_text("x" * 2048)
    cfg = tmp_path / "config.ini"
    cfg.write_text(f"[DEFAULT]\nhost = 127.0.0.1\nport = {remote.port}\nusername = {USER}\n"
                   f"password = {PASSWORD}\nknown_hosts_file = kh\ntimeout = 10\n"
                   f"[PATHS]\nremote_upload_dir = /in\n[LOGGING]\nlog_file =\n", encoding="utf-8")
    gui = G.SFTPPilotGUI(tk_root, str(cfg), str(tmp_path / "tasks.json"))
    yield gui
    gui.shutdown()
    for widget in tk_root.winfo_children():
        widget.destroy()
    tk_root.update()
    gc.collect()  # on the main thread, while nothing else is running


def pump(app, condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end and not condition():
        app.root.update()
        time.sleep(0.02)
    return condition()


def connect(app):
    app.connect()
    assert pump(app, lambda: app.sftp_handler is not None and not app.busy)


def browser(app):
    return next(w for w in app.root.winfo_children() if w.winfo_class() == "Toplevel")


def rows(b):
    return [b.tree.item(i)["values"][0] for i in b.tree.get_children()]


def test_pure_helpers():
    assert human_size(0) == "0 B" and human_size(1023) == "1023 B"
    assert human_size(2048) == "2.0 KB" and human_size(5 * 1024 ** 2) == "5.0 MB"
    assert start_folder("", "/in") == "/in"
    assert start_folder("/in/*.csv") == "/in"
    assert start_folder("/in/file.csv") == "/in"
    assert start_folder("/in/") == "/in/"
    assert start_folder("file.csv", "/x") == "/x"


def test_browser_refused_when_not_connected(app, dialogs):
    app.open_remote_browser(app.upload_remote_entry, MODE_FOLDER)
    assert dialogs[-1][0] == "showerror"
    assert not [w for w in app.root.winfo_children() if w.winfo_class() == "Toplevel"]


def test_browser_navigation_and_selection(app):
    connect(app)
    app.open_remote_browser(app.upload_remote_entry, MODE_FOLDER, add_slash=True)
    b = browser(app)
    assert pump(app, lambda: rows(b))
    assert b.path == "/in" and rows(b) == ["2026/", "a.csv", "b.csv"]  # opened at remote_upload_dir

    b.tree.selection_set("2026")
    b._on_double_click()
    assert pump(app, lambda: b.path == "/in/2026")
    b.go_up()
    assert pump(app, lambda: b.path == "/in")
    b.select()  # folder mode, nothing selected: the open folder
    assert app.upload_remote_entry.get() == "/in/"

    app.open_remote_browser(app.delete_remote_entry, MODE_FILE)
    b = browser(app)
    assert pump(app, lambda: rows(b))
    b.tree.selection_set("2026")
    b.select()  # a folder cannot be chosen in file mode: it is opened
    assert pump(app, lambda: b.path == "/in/2026")
    b.go_up()
    assert pump(app, lambda: b.path == "/in")
    b.tree.selection_set("b.csv")
    b._on_double_click()
    assert app.delete_remote_entry.get() == "/in/b.csv"


def test_browser_starts_from_a_pattern_and_falls_back_to_root(app):
    connect(app)
    app._set_entry(app.download_remote_entry, "/in/*.csv")
    app.open_remote_browser(app.download_remote_entry, MODE_ANY)
    b = browser(app)
    assert pump(app, lambda: rows(b))
    assert b.path == "/in"
    b.close()

    app._set_entry(app.download_remote_entry, "/gone/file.txt")
    app.open_remote_browser(app.download_remote_entry, MODE_ANY)
    b = browser(app)
    assert pump(app, lambda: b.path == "/" and rows(b))
    assert rows(b) == ["in/", "readme.txt"]


def test_browser_error_busy_guard_and_close_mid_load(app):
    connect(app)
    app.open_remote_browser(app.download_remote_entry, MODE_ANY)
    b = browser(app)
    assert pump(app, lambda: rows(b))
    b.navigate("/does/not/exist")
    assert pump(app, lambda: "Cannot open" in b.status.cget("text"))
    assert rows(b), "the old listing stays when a folder cannot be opened"

    app.busy = True
    b.navigate("/in")
    assert "running" in b.status.cget("text")
    app.busy = False

    b.navigate("/in")
    b.close()  # window goes away while the listing is in flight
    assert pump(app, lambda: not app.busy)


def test_task_browse_picks_remote_or_local_by_task_type(app):
    connect(app)
    app.task_type_var.set("delete")
    app.browse_task_path("source")
    b = browser(app)
    assert pump(app, lambda: rows(b)) and b.path == "/in"
    b.close()
    app.task_type_var.set("upload")
    app.browse_task_path("dest")
    b = browser(app)
    assert pump(app, lambda: rows(b))
    b.close()


def test_ask_policy_dialog_trusts_or_refuses(app, dialogs, tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text(cfg.read_text().replace("known_hosts_file = kh", "known_hosts_file = kh\nhost_key_policy = ask"))
    app.load_configuration()

    dialogs.answer = False
    app.connect()
    assert pump(app, lambda: not app.busy)
    assert app.sftp_handler is None
    assert [d for d in dialogs if d[0] == "askyesno"], "no fingerprint dialog was shown"
    assert "SHA256:" in dialogs[[d[0] for d in dialogs].index("askyesno")][1][1]
    assert (tmp_path / "kh").read_text(encoding="utf-8") == ""

    dialogs.answer = True
    app.connect()
    assert pump(app, lambda: not app.busy)
    assert app.sftp_handler is not None
    assert "127.0.0.1" in (tmp_path / "kh").read_text(encoding="utf-8")
