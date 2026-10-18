"""
Shared fixtures.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import pytest

pytest.importorskip("asyncssh")

from sftp_server import SFTPServer  # noqa: E402


@pytest.fixture
def remote(tmp_path):
    """A running SFTP server whose root is <tmp_path>/remote"""
    root = tmp_path / "remote"
    root.mkdir()
    with SFTPServer(root) as server:
        yield server
