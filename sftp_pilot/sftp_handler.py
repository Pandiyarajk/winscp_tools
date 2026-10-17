"""
SFTP protocol handler for file operations (paramiko based).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import logging
import os
import posixpath
import stat
from typing import Any, Callable, Dict, List, Optional

import paramiko

ProgressCallback = Callable[[int, int], None]


class SFTPHandler:
    """Handles SFTP operations against one server"""

    def __init__(self, host: str, port: int, username: str,
                 password: str = '', private_key_path: str = '', protocol: str = 'sftp',
                 private_key_passphrase: str = '', host_key_policy: str = 'accept_new',
                 known_hosts_file: str = 'known_hosts', timeout: float = 30.0):
        """
        Initialize the handler

        Args:
            host: Server hostname or IP
            port: Connection port
            username: Username for authentication
            password: Password for authentication (optional if using a key)
            private_key_path: Path to a private key file (RSA, ECDSA or Ed25519)
            protocol: Only 'sftp' is supported
            private_key_passphrase: Passphrase for an encrypted private key
            host_key_policy: 'accept_new' trusts a host on first connect and
                rejects a changed key; 'reject' only connects to hosts already
                known; 'auto_add' accepts any key (insecure, testing only)
            known_hosts_file: File where accepted host keys are stored
            timeout: Connect and authentication timeout in seconds
        """
        if protocol != 'sftp':
            raise ValueError(f"Unsupported protocol '{protocol}': only 'sftp' is supported")

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key_path = private_key_path
        self.private_key_passphrase = private_key_passphrase
        self.protocol = protocol
        self.host_key_policy = host_key_policy
        self.known_hosts_file = known_hosts_file
        self.timeout = timeout

        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None
        self.last_error = ""
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_config(cls, conn: Dict[str, Any]) -> 'SFTPHandler':
        """
        Build a handler from ConfigManager.get_connection_details() output

        Args:
            conn: Connection details dictionary

        Returns:
            A handler that is not yet connected
        """
        return cls(
            host=conn['host'],
            port=conn['port'],
            username=conn['username'],
            password=conn.get('password', ''),
            private_key_path=conn.get('private_key_path', ''),
            protocol=conn.get('protocol', 'sftp'),
            private_key_passphrase=conn.get('private_key_passphrase', ''),
            host_key_policy=conn.get('host_key_policy', 'accept_new'),
            known_hosts_file=conn.get('known_hosts_file', 'known_hosts'),
            timeout=conn.get('timeout', 30.0),
        )

    def _configure_host_keys(self, client: paramiko.SSHClient) -> None:
        """Load known host keys and set the missing-key policy"""
        try:
            client.load_system_host_keys()
        except OSError as e:
            self.logger.warning(f"Could not read system known_hosts: {e}")

        if self.host_key_policy == 'reject':
            if self.known_hosts_file and os.path.exists(self.known_hosts_file):
                client.load_host_keys(self.known_hosts_file)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            return

        if self.host_key_policy == 'auto_add':
            self.logger.warning("host_key_policy=auto_add: server identity is NOT verified")
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            return

        # accept_new: remember unknown hosts in known_hosts_file. A key that
        # differs from a remembered one raises BadHostKeyException in connect().
        if self.known_hosts_file:
            directory = os.path.dirname(os.path.abspath(self.known_hosts_file))
            os.makedirs(directory, exist_ok=True)
            if not os.path.exists(self.known_hosts_file):
                open(self.known_hosts_file, 'a', encoding='utf-8').close()
            client.load_host_keys(self.known_hosts_file)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self) -> bool:
        """
        Establish connection to remote server

        Returns:
            True if connection successful, False otherwise (see last_error)
        """
        self.disconnect(quiet=True)
        self.last_error = ""
        try:
            client = paramiko.SSHClient()
            self._configure_host_keys(client)

            kwargs: Dict[str, Any] = {
                'port': self.port,
                'username': self.username,
                'timeout': self.timeout,
                'auth_timeout': self.timeout,
                'banner_timeout': self.timeout,
            }
            if self.private_key_path:
                if not os.path.exists(self.private_key_path):
                    raise FileNotFoundError(f"Private key not found: {self.private_key_path}")
                # key_filename lets paramiko pick the key type (RSA, ECDSA, Ed25519)
                kwargs['key_filename'] = self.private_key_path
                kwargs['passphrase'] = self.private_key_passphrase or None
                kwargs['look_for_keys'] = False
                kwargs['allow_agent'] = False
            if self.password:
                kwargs['password'] = self.password

            client.connect(self.host, **kwargs)
            self.ssh_client = client
            self.sftp_client = client.open_sftp()
            self.logger.info(f"Connected to {self.host}:{self.port}")
            return True

        except paramiko.BadHostKeyException as e:
            self.last_error = (
                f"Host key for {self.host} does not match the one on record in "
                f"{self.known_hosts_file}. This can mean a man-in-the-middle attack. "
                f"If the server key really changed, remove its line from that file. ({e})"
            )
        except paramiko.SSHException as e:
            if 'not found in known_hosts' in str(e):
                self.last_error = (
                    f"{self.host} is not a known host and host_key_policy is 'reject'. "
                    f"Add its key to known_hosts or use host_key_policy = accept_new."
                )
            else:
                self.last_error = str(e)
        except Exception as e:
            self.last_error = str(e) or e.__class__.__name__

        self.logger.error(f"Connection failed: {self.last_error}")
        self.disconnect(quiet=True)
        return False

    def is_connected(self) -> bool:
        """
        Report whether the SSH transport is still alive

        Returns:
            True while the connection is usable
        """
        if not self.ssh_client or not self.sftp_client:
            return False
        transport = self.ssh_client.get_transport()
        return bool(transport and transport.is_active())

    def disconnect(self, quiet: bool = False) -> None:
        """
        Close connection to remote server

        Args:
            quiet: Skip the log line (used for internal cleanup)
        """
        was_open = self.ssh_client is not None
        for closable in (self.sftp_client, self.ssh_client):
            if closable:
                try:
                    closable.close()
                except Exception as e:
                    self.logger.debug(f"Error while closing: {e}")
        self.sftp_client = None
        self.ssh_client = None
        if was_open and not quiet:
            self.logger.info("Disconnected from server")

    def _require_connection(self) -> paramiko.SFTPClient:
        if not self.sftp_client:
            raise ConnectionError("Not connected to server")
        return self.sftp_client

    def upload_file(self, local_path: str, remote_path: str,
                    progress_callback: Optional[ProgressCallback] = None) -> bool:
        """
        Upload file to remote server

        Args:
            local_path: Local file path
            remote_path: Remote destination path (POSIX style)
            progress_callback: Optional callback(sent_bytes, total_bytes)

        Returns:
            True if upload successful, False otherwise
        """
        try:
            sftp = self._require_connection()
            if not os.path.isfile(local_path):
                self.logger.error(f"Local file not found: {local_path}")
                return False

            remote_path = remote_path.replace('\\', '/')
            if remote_path.endswith('/'):
                remote_path = posixpath.join(remote_path, os.path.basename(local_path))

            self._ensure_remote_dir(posixpath.dirname(remote_path))

            file_size = os.path.getsize(local_path)
            self.logger.info(f"Uploading {local_path} to {remote_path} ({file_size} bytes)")
            sftp.put(local_path, remote_path, callback=progress_callback)
            self.logger.info(f"Upload completed: {remote_path}")
            return True

        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str,
                      progress_callback: Optional[ProgressCallback] = None) -> bool:
        """
        Download file from remote server

        Args:
            remote_path: Remote file path (POSIX style)
            local_path: Local destination path; an existing directory keeps the remote name
            progress_callback: Optional callback(received_bytes, total_bytes)

        Returns:
            True if download successful, False otherwise
        """
        try:
            sftp = self._require_connection()
            remote_path = remote_path.replace('\\', '/')
            if os.path.isdir(local_path):
                local_path = os.path.join(local_path, posixpath.basename(remote_path))

            local_dir = os.path.dirname(local_path)
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)

            self.logger.info(f"Downloading {remote_path} to {local_path}")
            # Download to a temporary name so a failed transfer never leaves a
            # truncated file where a good one is expected.
            partial = local_path + '.part'
            try:
                sftp.get(remote_path, partial, callback=progress_callback)
                os.replace(partial, local_path)
            finally:
                if os.path.exists(partial):
                    os.remove(partial)

            self.logger.info(f"Download completed: {local_path}")
            return True

        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def delete_file(self, remote_path: str) -> bool:
        """
        Delete file from remote server

        Args:
            remote_path: Remote file path to delete

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self._require_connection().remove(remote_path.replace('\\', '/'))
            self.logger.info(f"Deleted: {remote_path}")
            return True

        except Exception as e:
            self.logger.error(f"Deletion failed: {e}")
            return False

    def list_files(self, remote_path: str) -> List[str]:
        """
        List files in remote directory

        Args:
            remote_path: Remote directory path

        Returns:
            Sorted list of names; directories carry a trailing '/'
        """
        try:
            entries = self._require_connection().listdir_attr(remote_path.replace('\\', '/'))
            names = []
            for entry in entries:
                is_dir = entry.st_mode is not None and stat.S_ISDIR(entry.st_mode)
                names.append(entry.filename + ('/' if is_dir else ''))
            return sorted(names)
        except Exception as e:
            self.logger.error(f"Failed to list files: {e}")
            return []

    def file_exists(self, remote_path: str) -> bool:
        """
        Check if remote file exists

        Args:
            remote_path: Remote file path

        Returns:
            True if file exists, False otherwise
        """
        try:
            self._require_connection().stat(remote_path.replace('\\', '/'))
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            self.logger.error(f"Error checking file existence: {e}")
            return False

    def _ensure_remote_dir(self, remote_dir: str) -> None:
        """
        Ensure remote directory exists, create if not

        Args:
            remote_dir: Remote directory path (POSIX style)
        """
        if not remote_dir or remote_dir in ('/', '.'):
            return

        sftp = self._require_connection()
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            self._ensure_remote_dir(posixpath.dirname(remote_dir.rstrip('/')))
            sftp.mkdir(remote_dir)
            self.logger.info(f"Created remote directory: {remote_dir}")
