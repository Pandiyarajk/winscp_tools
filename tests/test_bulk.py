"""
Folder and wildcard transfers against a real SFTP server.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import os
import threading
from datetime import datetime, timedelta

import pytest

pytest.importorskip("asyncssh")

from sftp_server import conn_for, connected  # noqa: E402

from sftp_pilot.runner import make_task_executor  # noqa: E402
from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskStatus, TaskType  # noqa: E402
from sftp_pilot.sftp_handler import BulkResult, RemoteEntry, SFTPHandler  # noqa: E402


def tree(root):
    """Relative posix paths of every file under root"""
    return sorted(str(p.relative_to(root)).replace(os.sep, "/")
                  for p in root.rglob("*") if p.is_file())


@pytest.fixture
def local_tree(tmp_path):
    base = tmp_path / "out"
    (base / "sub" / "deep").mkdir(parents=True)
    (base / "a.csv").write_text("a")
    (base / "b.csv").write_text("b")
    (base / "notes.txt").write_text("n")
    (base / "sub" / "c.csv").write_text("c")
    (base / "sub" / "deep" / "d.bin").write_bytes(os.urandom(1000))
    return base


def test_upload_folder_keeps_structure(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    try:
        result = h.upload(str(local_tree), "/backup")
    finally:
        h.disconnect()
    assert result.ok and result.done == 5
    assert tree(tmp_path / "remote") == [
        "backup/out/a.csv", "backup/out/b.csv", "backup/out/notes.txt",
        "backup/out/sub/c.csv", "backup/out/sub/deep/d.bin"]
    assert (tmp_path / "remote/backup/out/sub/deep/d.bin").read_bytes() == \
        (local_tree / "sub/deep/d.bin").read_bytes()


def test_upload_pattern_takes_matching_files_only(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    try:
        result = h.upload(str(local_tree / "*.csv"), "/in/")
        assert result.ok and result.done == 2
        assert h.upload(str(local_tree / "**" / "*.csv"), "/all").done == 3  # ** reaches subfolders
    finally:
        h.disconnect()
    assert tree(tmp_path / "remote") == ["all/a.csv", "all/b.csv", "all/c.csv", "in/a.csv", "in/b.csv"]


def test_nothing_matching_is_a_failure_not_a_success(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    try:
        result = h.upload(str(local_tree / "*.xyz"), "/in/")
        assert not result.ok and result.done == 0 and "No files match" in result.message
        assert "No files match" in h.last_error
        empty = tmp_path / "empty"
        empty.mkdir()
        assert not h.upload(str(empty), "/in/").ok
    finally:
        h.disconnect()


def test_single_file_behaves_as_before(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    try:
        assert h.upload(str(local_tree / "a.csv"), "/one/").ok  # trailing slash keeps the name
        assert h.upload(str(local_tree / "b.csv"), "/one/renamed.csv").ok
        missing = h.upload(str(local_tree / "missing.csv"), "/one/")
        assert not missing.ok and missing.failed and "not found" in missing.failed[0][1].lower()
    finally:
        h.disconnect()
    assert tree(tmp_path / "remote") == ["one/a.csv", "one/renamed.csv"]


def test_one_bad_file_does_not_stop_the_rest(remote, tmp_path, local_tree):
    (tmp_path / "remote/out").mkdir()
    (tmp_path / "remote/out/b.csv").mkdir()  # a folder where b.csv must go: that file fails
    h = connected(remote, tmp_path)
    try:
        result = h.upload(str(local_tree), "/")
    finally:
        h.disconnect()
    assert not result.ok
    assert result.done == 4 and [name for name, _ in result.failed] == ["out/b.csv"]
    assert "1 of 5 failed" in result.summary() and "out/b.csv" in result.summary()
    assert (tmp_path / "remote/out/a.csv").exists() and (tmp_path / "remote/out/sub/c.csv").exists()
    assert not [p for p in (tmp_path / "remote").rglob("*.part")], ".part file left behind"


def test_download_folder_and_pattern(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    try:
        assert h.upload(str(local_tree), "/data").ok
        dest = tmp_path / "got"
        folder = h.download("/data/out", str(dest))
        assert folder.ok and folder.done == 5
        assert tree(dest) == ["out/a.csv", "out/b.csv", "out/notes.txt", "out/sub/c.csv", "out/sub/deep/d.bin"]
        assert (dest / "out/sub/deep/d.bin").read_bytes() == (local_tree / "sub/deep/d.bin").read_bytes()

        dest2 = tmp_path / "got2"
        matched = h.download("/data/out/*.csv", str(dest2))
        assert matched.ok and matched.done == 2 and tree(dest2) == ["a.csv", "b.csv"]

        bad = h.download("/data/*/x.csv", str(tmp_path / "got3"))
        assert not bad.ok and "last part" in bad.message
        none = h.download("/data/out/*.xyz", str(tmp_path / "got4"))
        assert not none.ok and "No files match" in none.message
    finally:
        h.disconnect()


def test_single_download_behaves_as_before(remote, tmp_path):
    (tmp_path / "remote/f.txt").write_text("hello")
    out = tmp_path / "out"
    out.mkdir()
    h = connected(remote, tmp_path)
    try:
        assert h.download("/f.txt", str(out)).ok  # existing folder keeps the name
        assert h.download("/f.txt", str(out / "renamed.txt")).ok
        assert not h.download("/missing.txt", str(out)).ok
    finally:
        h.disconnect()
    assert tree(out) == ["f.txt", "renamed.txt"]


def test_server_sent_names_cannot_escape_the_destination(remote, tmp_path, monkeypatch):
    h = connected(remote, tmp_path)
    (tmp_path / "remote/ok.txt").write_text("fine")
    real = h.list_dir
    evil = [RemoteEntry("..\\..\\evil.txt", False, 1, 0), RemoteEntry("..", False, 1, 0),
            RemoteEntry("C:evil.txt", False, 1, 0), RemoteEntry("a/b.txt", False, 1, 0)]
    monkeypatch.setattr(h, "list_dir", lambda path: real(path) + evil)
    dest = tmp_path / "dest" / "inner"
    try:
        result = h.download("/*", str(dest))  # every injected name matches the pattern
    finally:
        h.disconnect()
    assert result.done == 1 and tree(dest) == ["ok.txt"]
    assert len(result.failed) == 4 and all("unsafe name" in why for _, why in result.failed)
    assert not (tmp_path / "dest" / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()
    assert not result.ok  # skipped names are reported, not hidden


def test_symbolic_links_are_skipped(remote, tmp_path):
    target = tmp_path / "remote" / "real.txt"
    target.write_text("data")
    try:
        os.symlink(target, tmp_path / "remote" / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    h = connected(remote, tmp_path)
    try:
        result = h.download("/*.txt", str(tmp_path / "got"))
    finally:
        h.disconnect()
    assert tree(tmp_path / "got") == ["real.txt"]
    assert any("symbolic link" in why for _, why in result.failed)


def test_cancel_between_files_keeps_finished_ones(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    cancel = threading.Event()
    try:
        result = h.upload(str(local_tree), "/c", cancel_event=cancel,
                          item_callback=lambda i, n, name: cancel.set() if i == 2 else None)
    finally:
        h.disconnect()
    assert result.cancelled and not result.ok and result.done == 1
    assert len(tree(tmp_path / "remote")) == 1
    assert not [p for p in (tmp_path / "remote").rglob("*.part")]


def test_item_callback_counts_files(remote, tmp_path, local_tree):
    h = connected(remote, tmp_path)
    seen = []
    try:
        h.upload(str(local_tree / "*.csv"), "/in/", item_callback=lambda i, n, name: seen.append((i, n, name)))
    finally:
        h.disconnect()
    assert seen == [(1, 2, "a.csv"), (2, 2, "b.csv")]


def test_list_dir_types_and_order(remote, tmp_path):
    (tmp_path / "remote/Zdir").mkdir()
    (tmp_path / "remote/adir").mkdir()
    (tmp_path / "remote/b.txt").write_text("12345")
    h = connected(remote, tmp_path)
    try:
        entries = h.list_dir("/")
        assert [(e.name, e.is_dir) for e in entries] == [("adir", True), ("Zdir", True), ("b.txt", False)]
        assert entries[2].size == 5
        assert h.is_remote_dir("/adir") and not h.is_remote_dir("/b.txt") and not h.is_remote_dir("/nope")
    finally:
        h.disconnect()


def test_scheduled_pattern_upload_and_partial_failure_message(remote, tmp_path, local_tree):
    sched = TaskScheduler(str(tmp_path / "tasks.json"))
    sched.set_task_executor(make_task_executor(lambda _server: conn_for(remote, tmp_path)))
    past = datetime.now() - timedelta(seconds=1)
    sched.add_task(ScheduledTask("bulk-0001", TaskType.UPLOAD, str(local_tree / "*.csv"), "/nightly/",
                                 scheduled_time=past))
    (tmp_path / "remote/clash").mkdir()
    (tmp_path / "remote/clash/a.csv").mkdir()
    sched.add_task(ScheduledTask("bulk-0002", TaskType.UPLOAD, str(local_tree / "*.csv"), "/clash/",
                                 scheduled_time=past))
    records = {r["task_id"]: r for r in sched.run_due_tasks()}
    assert records["bulk-0001"]["result"] == "ok"
    assert tree(tmp_path / "remote/nightly") == ["a.csv", "b.csv"]
    assert records["bulk-0002"]["result"] == "failed"
    assert "1 of 2 failed" in records["bulk-0002"]["error"] and "a.csv" in records["bulk-0002"]["error"]
    assert sched.get_task("bulk-0002").status == TaskStatus.FAILED


def test_bulk_result_summaries():
    assert BulkResult(done=3).summary() == "3 file(s) transferred" and BulkResult(done=3).ok
    assert not BulkResult().ok  # nothing transferred is never "ok"
    many = BulkResult(done=1, failed=[(f"f{i}", "boom") for i in range(5)])
    assert many.summary().startswith("5 of 6 failed: f0: boom; f1: boom; f2: boom (+2 more)")
    assert SFTPHandler._safe_name("report.csv") and not SFTPHandler._safe_name("..")
