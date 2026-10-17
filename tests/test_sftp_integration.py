"""
End-to-end tests against a real SFTP server (asyncssh, in-process, chrooted
to a temporary folder). Skipped when asyncssh is not installed.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

import asyncio
import os
import threading
from datetime import datetime, timedelta

import pytest

asyncssh = pytest.importorskip("asyncssh")

from sftp_pilot.runner import make_task_executor  # noqa: E402
from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskStatus, TaskType  # noqa: E402
from sftp_pilot.sftp_handler import SFTPHandler  # noqa: E402

USER, PASSWORD = "tester", "s3cret"


class SFTPServer:
    """Runs an asyncssh SFTP server on its own event loop thread"""

    def __init__(self, root, authorized_key=None):
        self.root = str(root)
        self.authorized_key = authorized_key
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.server = asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(10)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def _start(self):
        outer = self

        class Auth(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def password_auth_supported(self):
                return True

            def validate_password(self, username, password):
                return username == USER and password == PASSWORD

            def public_key_auth_supported(self):
                return outer.authorized_key is not None

            def validate_public_key(self, username, key):
                return username == USER and key == outer.authorized_key

        return await asyncssh.create_server(
            Auth, "127.0.0.1", 0, server_host_keys=[self.host_key],
            sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=self.root.encode()),
        )

    def __exit__(self, *exc):
        # No wait_closed(): it waits for every connection, and a client the
        # test refused (bad host key, wrong password) may never say goodbye.
        self.loop.call_soon_threadsafe(self.server.close)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def remote(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    with SFTPServer(root) as server:
        yield server


def conn_for(server, tmp_path, **kw):
    conn = dict(host="127.0.0.1", port=server.port, username=USER, password=PASSWORD,
                known_hosts_file=str(tmp_path / "known_hosts"), timeout=10)
    conn.update(kw)
    return conn


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
