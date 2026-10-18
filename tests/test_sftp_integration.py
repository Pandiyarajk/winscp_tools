"""
End-to-end tests against a real SFTP server (asyncssh, in-process, chrooted
to a temporary folder). Skipped when asyncssh is not installed.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

import os
import threading
from datetime import datetime, timedelta

import pytest

asyncssh = pytest.importorskip("asyncssh")

from sftp_pilot.runner import make_task_executor  # noqa: E402
from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskStatus, TaskType  # noqa: E402
from sftp_pilot.sftp_handler import CANCELLED, SFTPHandler  # noqa: E402
from sftp_server import SFTPServer, conn_for, connected  # noqa: E402

def test_transfer_round_trip(remote, tmp_path):
    local = tmp_path / "local.bin"
    payload = os.urandom(300_000)
    local.write_bytes(payload)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")

    h = SFTPHandler.from_config(conn_for(remote, tmp_path))
    assert h.connect(), h.last_error
    try:
        progress = []
        assert h.upload_file(str(local), "/deep/new/dir/remote.bin", lambda d, t: progress.append((d, t)))
        assert progress and progress[-1] == (len(payload), len(payload))
        assert (tmp_path / "remote/deep/new/dir/remote.bin").read_bytes() == payload

        assert h.upload_file(str(empty), "/deep/")  # trailing slash keeps the local name
        assert h.file_exists("/deep/empty.txt")
        assert h.list_files("/deep") == ["empty.txt", "new/"]

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        assert h.download_file("/deep/new/dir/remote.bin", str(out_dir))
        assert (out_dir / "remote.bin").read_bytes() == payload

        assert not h.download_file("/missing.bin", str(out_dir / "missing.bin"))
        assert not (out_dir / "missing.bin").exists()
        assert not (out_dir / "missing.bin.part").exists(), "partial file left behind"

        assert h.delete_file("/deep/empty.txt")
        assert not h.file_exists("/deep/empty.txt")
    finally:
        h.disconnect()
    assert not h.is_connected()


def test_accept_new_remembers_and_detects_a_changed_key(remote, tmp_path):
    conn = conn_for(remote, tmp_path)
    h = SFTPHandler.from_config(conn)
    assert h.connect(), h.last_error
    h.disconnect()
    known = (tmp_path / "known_hosts").read_text()
    assert f"[127.0.0.1]:{remote.port}" in known

    # Same host:port, different key on record: must be refused.
    impostor = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().split()[:2]
    (tmp_path / "known_hosts").write_text(f"[127.0.0.1]:{remote.port} {' '.join(impostor)}\n")
    h = SFTPHandler.from_config(conn)
    assert not h.connect()
    assert "does not match" in h.last_error


def test_reject_policy_refuses_unknown_host(remote, tmp_path):
    h = SFTPHandler.from_config(conn_for(remote, tmp_path, host_key_policy="reject"))
    assert not h.connect()
    assert "not a known host" in h.last_error


def test_wrong_password_reports_error(remote, tmp_path):
    h = SFTPHandler.from_config(conn_for(remote, tmp_path, password="nope"))
    assert not h.connect()
    assert h.last_error


def test_encrypted_ed25519_key(tmp_path):
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    key_file = tmp_path / "id_ed25519"
    key_file.write_bytes(client_key.export_private_key("openssh", passphrase="pw"))
    root = tmp_path / "remote"
    root.mkdir()
    with SFTPServer(root, authorized_key=client_key.convert_to_public()) as server:
        h = SFTPHandler.from_config(conn_for(
            server, tmp_path, password="", private_key_path=str(key_file),
            private_key_passphrase="pw"))
        assert h.connect(), h.last_error
        h.disconnect()


def test_scheduler_runs_task_on_its_own_connection(remote, tmp_path):
    src = tmp_path / "nightly.txt"
    src.write_text("backup")
    sched = TaskScheduler(str(tmp_path / "tasks.json"))
    sched.set_task_executor(make_task_executor(lambda: conn_for(remote, tmp_path)))
    sched.add_task(ScheduledTask("task-0001", TaskType.UPLOAD, str(src), "/backups/",
                                 datetime.now() - timedelta(seconds=1)))
    sched.run_due_tasks()
    assert sched.get_task("task-0001").status == TaskStatus.COMPLETED
    assert (tmp_path / "remote/backups/nightly.txt").read_text() == "backup"


def test_scheduled_failure_records_the_reason(remote, tmp_path):
    sched = TaskScheduler(str(tmp_path / "tasks.json"))
    sched.set_task_executor(make_task_executor(lambda: conn_for(remote, tmp_path)))
    sched.add_task(ScheduledTask("task-0002", TaskType.DELETE, "/no/such/file",
                                 scheduled_time=datetime.now() - timedelta(seconds=1)))
    record = sched.run_due_tasks()[0]
    assert record["result"] == "failed"
    assert record["error"].startswith("delete failed:") and "see log" not in record["error"]


def remote_names(tmp_path):
    return sorted(p.name for p in (tmp_path / "remote").iterdir())


def test_atomic_upload_replaces_existing_file(remote, tmp_path):
    (tmp_path / "remote/report.csv").write_text("old")
    src = tmp_path / "report.csv"
    src.write_text("new contents")
    h = connected(remote, tmp_path)
    seen = []
    try:
        assert h.upload_file(str(src), "/report.csv",
                             lambda d, t: seen.append(remote_names(tmp_path)))
    finally:
        h.disconnect()
    assert (tmp_path / "remote/report.csv").read_text() == "new contents"
    assert remote_names(tmp_path) == ["report.csv"]
    assert any("report.csv.part" in names for names in seen), "upload did not go via .part"


def test_atomic_upload_without_posix_rename(remote, tmp_path):
    (tmp_path / "remote/report.csv").write_text("old")
    src = tmp_path / "report.csv"
    src.write_text("new contents")
    h = connected(remote, tmp_path)

    def unsupported(*_a):
        raise IOError("Operation unsupported")

    h.sftp_client.posix_rename = unsupported
    try:
        assert h.upload_file(str(src), "/report.csv"), h.last_error
    finally:
        h.disconnect()
    assert (tmp_path / "remote/report.csv").read_text() == "new contents"
    assert remote_names(tmp_path) == ["report.csv"], "a .part or .old file was left behind"


def test_non_atomic_upload_writes_in_place(remote, tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x" * 100_000)
    h = connected(remote, tmp_path, atomic_uploads=False)
    seen = []
    try:
        assert h.upload_file(str(src), "/a.txt", lambda d, t: seen.append(remote_names(tmp_path)))
    finally:
        h.disconnect()
    assert not any("a.txt.part" in names for names in seen)


def test_cancelled_upload_keeps_the_old_file(remote, tmp_path):
    (tmp_path / "remote/big.bin").write_bytes(b"old")
    src = tmp_path / "big.bin"
    src.write_bytes(os.urandom(2_000_000))
    cancel = threading.Event()
    h = connected(remote, tmp_path)
    try:
        ok = h.upload_file(str(src), "/big.bin", lambda d, t: cancel.set(), cancel_event=cancel)
        assert not ok and h.last_error == CANCELLED
        assert h.is_connected(), "cancel broke the connection"
        assert h.file_exists("/big.bin")
    finally:
        h.disconnect()
    assert (tmp_path / "remote/big.bin").read_bytes() == b"old"
    assert remote_names(tmp_path) == ["big.bin"]


def test_cancelled_download_leaves_nothing(remote, tmp_path):
    (tmp_path / "remote/big.bin").write_bytes(os.urandom(2_000_000))
    cancel = threading.Event()
    out = tmp_path / "out"
    out.mkdir()
    h = connected(remote, tmp_path)
    try:
        ok = h.download_file("/big.bin", str(out), lambda d, t: cancel.set(), cancel_event=cancel)
        assert not ok and h.last_error == CANCELLED
    finally:
        h.disconnect()
    assert list(out.iterdir()) == []


def test_ask_policy_shows_fingerprint_and_remembers(remote, tmp_path):
    from sftp_pilot.sftp_handler import SFTPHandler as H
    expected = remote.host_key.get_fingerprint("sha256")  # asyncssh: 'SHA256:...'
    asked = []

    def yes(host, key_type, fp):
        asked.append((host, key_type, fp))
        return True

    conn = conn_for(remote, tmp_path, host_key_policy="ask")
    h = H.from_config(conn, confirm_host_key=yes)
    assert h.connect(), h.last_error
    h.disconnect()
    assert len(asked) == 1
    assert asked[0][1:] == ("ssh-ed25519", expected)
    assert f"[127.0.0.1]:{remote.port}" in (tmp_path / "known_hosts").read_text()

    h = H.from_config(conn, confirm_host_key=lambda *a: pytest.fail("asked about a known host"))
    assert h.connect(), h.last_error
    h.disconnect()


def test_ask_policy_refusal_saves_nothing(remote, tmp_path):
    conn = conn_for(remote, tmp_path, host_key_policy="ask")
    h = SFTPHandler.from_config(conn, confirm_host_key=lambda *a: False)
    assert not h.connect() and "not accepted" in h.last_error
    assert (tmp_path / "known_hosts").read_text() == ""


def test_ask_policy_without_a_prompt_refuses(remote, tmp_path):
    # what a scheduled task or --run-due sees: nobody to ask
    h = SFTPHandler.from_config(conn_for(remote, tmp_path, host_key_policy="ask"))
    assert not h.connect() and "nobody can be asked" in h.last_error
    assert (tmp_path / "known_hosts").read_text() == ""


def test_accept_new_logs_the_fingerprint(remote, tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="sftp_pilot.sftp_handler"):
        h = connected(remote, tmp_path)
        h.disconnect()
    assert remote.host_key.get_fingerprint("sha256") in caplog.text
