"""
Shared test helpers: an in-process SFTP server (asyncssh) chrooted to a folder.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import asyncio
import threading

import pytest

asyncssh = pytest.importorskip("asyncssh")

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
        # Cancel what is left instead, so asyncio does not complain about
        # destroyed pending tasks at exit.
        async def shutdown():
            self.server.close()
            others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in others:
                task.cancel()
            await asyncio.gather(*others, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def conn_for(server, tmp_path, **kw):
    conn = dict(host="127.0.0.1", port=server.port, username=USER, password=PASSWORD,
                known_hosts_file=str(tmp_path / "known_hosts"), timeout=10)
    conn.update(kw)
    return conn


def connected(remote, tmp_path, **kw):
    h = SFTPHandler.from_config(conn_for(remote, tmp_path, **kw))
    assert h.connect(), h.last_error
    return h
