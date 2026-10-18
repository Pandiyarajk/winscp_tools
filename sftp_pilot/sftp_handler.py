"""
SFTP protocol handler for file operations (paramiko based).

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import base64
import fnmatch
import glob
import hashlib
import logging
import os
import posixpath
import stat
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import paramiko

ProgressCallback = Callable[[int, int], None]

CANCELLED = "Cancelled"

# Called with (host, key_type, fingerprint) for a server not seen before;
# returns True to trust it. Runs on the connecting thread.
HostKeyPrompt = Callable[[str, str, str], bool]


def fingerprint(key: paramiko.PKey) -> str:
    """
    OpenSSH style SHA256 fingerprint of a host key

    Args:
        key: The server's public key

    Returns:
        For example 'SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8'
    """
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class _TrustAndLog(paramiko.MissingHostKeyPolicy):
    """accept_new: remember an unknown host, and say which key was trusted"""

    def __init__(self, known_hosts_file: str, logger: logging.Logger):
        self.known_hosts_file = known_hosts_file
        self.logger = logger

    def missing_host_key(self, client, hostname, key):
        client.get_host_keys().add(hostname, key.get_name(), key)
        if self.known_hosts_file:
            client.save_host_keys(self.known_hosts_file)
        self.logger.warning(
            f"Trusted new host {hostname} ({key.get_name()} {fingerprint(key)}). "
            f"Verify it out of band if this first connection matters.")


class _AskPolicy(paramiko.MissingHostKeyPolicy):
    """ask: show the fingerprint of an unknown host and trust it only on a yes"""

    def __init__(self, known_hosts_file: str, prompt: Optional[HostKeyPrompt],
                 logger: logging.Logger):
        self.known_hosts_file = known_hosts_file
        self.prompt = prompt
        self.logger = logger

    def missing_host_key(self, client, hostname, key):
        fp = fingerprint(key)
        if self.prompt is None:
            raise paramiko.SSHException(
                f"{hostname} is not a known host ({key.get_name()} {fp}) and nobody can be "
                f"asked here. Connect once interactively and accept it, or add it to known_hosts.")
        if not self.prompt(hostname, key.get_name(), fp):
            raise paramiko.SSHException(f"Host key for {hostname} ({fp}) was not accepted")
        client.get_host_keys().add(hostname, key.get_name(), key)
        if self.known_hosts_file:
            client.save_host_keys(self.known_hosts_file)
        self.logger.info(f"Trusted host {hostname} ({key.get_name()} {fp}) after confirmation")


GLOB_CHARS = "*?["


def has_wildcard(spec: str) -> bool:
    """True when a path contains a pattern character (* ? [)"""
    return any(c in spec for c in GLOB_CHARS)


@dataclass
class RemoteEntry:
    """One item of a remote directory listing"""
    name: str
    is_dir: bool
    size: int
    mtime: int
    is_link: bool = False


@dataclass
class BulkResult:
    """Outcome of an upload or download that may cover many files"""
    done: int = 0
    failed: List[Tuple[str, str]] = field(default_factory=list)  # (name, reason)
    cancelled: bool = False
    message: str = ""  # set when nothing could be attempted (no match, bad pattern)

    @property
    def ok(self) -> bool:
        """True when at least one file was transferred and nothing failed"""
        return self.done > 0 and not self.failed and not self.cancelled and not self.message

    def summary(self) -> str:
        """One line for a dialog, a log or a task's error message"""
        if self.message:
            return self.message
        total = self.done + len(self.failed)
        if self.cancelled:
            return f"{CANCELLED}: {self.done} file(s) completed before it stopped"
        if self.failed:
            shown = "; ".join(f"{name or '?'}: {why}" for name, why in self.failed[:3])
            more = f" (+{len(self.failed) - 3} more)" if len(self.failed) > 3 else ""
            return f"{len(self.failed)} of {total} failed: {shown}{more}"
        return f"{self.done} file(s) transferred"


class TransferCancelled(Exception):
    """Raised from the progress callback to abort a transfer"""


class SFTPHandler:
    """Handles SFTP operations against one server"""

    def __init__(self, host: str, port: int, username: str,
                 password: str = '', private_key_path: str = '', protocol: str = 'sftp',
                 private_key_passphrase: str = '', host_key_policy: str = 'accept_new',
                 known_hosts_file: str = 'known_hosts', timeout: float = 30.0,
                 atomic_uploads: bool = True, confirm_host_key: Optional[HostKeyPrompt] = None):
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
                rejects a changed key; 'ask' shows the fingerprint and trusts
                the host only if confirm_host_key says yes (no prompt available
                means reject); 'reject' only connects to hosts already known;
                'auto_add' accepts any key (insecure, testing only)
            known_hosts_file: File where accepted host keys are stored
            timeout: Connect and authentication timeout in seconds
            confirm_host_key: Prompt used by the 'ask' policy
            atomic_uploads: Upload to '<name>.part' and rename into place, so
                a failed upload never leaves a truncated file under the real name
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
        self.atomic_uploads = atomic_uploads
        self.confirm_host_key = confirm_host_key

        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None
        self.last_error = ""
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_config(cls, conn: Dict[str, Any],
                    confirm_host_key: Optional[HostKeyPrompt] = None) -> 'SFTPHandler':
        """
        Build a handler from ConfigManager.get_connection_details() output

        Args:
            conn: Connection details dictionary
            confirm_host_key: Prompt for the 'ask' host key policy

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
            atomic_uploads=conn.get('atomic_uploads', True),
            confirm_host_key=confirm_host_key,
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

        # accept_new and ask: remember hosts in known_hosts_file. A key that
        # differs from a remembered one raises BadHostKeyException in connect().
        if self.known_hosts_file:
            directory = os.path.dirname(os.path.abspath(self.known_hosts_file))
            os.makedirs(directory, exist_ok=True)
            if not os.path.exists(self.known_hosts_file):
                open(self.known_hosts_file, 'a', encoding='utf-8').close()
            client.load_host_keys(self.known_hosts_file)
        if self.host_key_policy == 'ask':
            client.set_missing_host_key_policy(
                _AskPolicy(self.known_hosts_file, self.confirm_host_key, self.logger))
        else:
            client.set_missing_host_key_policy(_TrustAndLog(self.known_hosts_file, self.logger))

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
                if not self.private_key_path:
                    # A password was configured: do not also offer the SSH agent's keys
                    # and ~/.ssh keys first. That is slow, and a server with a low
                    # MaxAuthTries can refuse the login before the password is tried.
                    kwargs['look_for_keys'] = False
                    kwargs['allow_agent'] = False

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

    @staticmethod
    def _progress(callback: Optional[ProgressCallback],
                  cancel_event: Optional[threading.Event]) -> Optional[ProgressCallback]:
        """Wrap a progress callback so a set cancel_event aborts the transfer"""
        if cancel_event is None:
            return callback

        def wrapped(done: int, total: int) -> None:
            if cancel_event.is_set():
                raise TransferCancelled()
            if callback:
                callback(done, total)

        return wrapped

    def _replace_remote(self, sftp: paramiko.SFTPClient, source: str, target: str) -> None:
        """
        Move source over target. posix-rename (OpenSSH) replaces in one step;
        without it, the old target is moved aside first and restored if the
        swap fails, so the target is never lost.
        """
        try:
            sftp.posix_rename(source, target)
            return
        except IOError as e:
            self.logger.debug(f"posix_rename unavailable ({e}); using rename")
        try:
            sftp.rename(source, target)  # works when the target does not exist yet
            return
        except IOError:
            if not self.file_exists(target):
                raise
        backup = target + '.old'
        sftp.rename(target, backup)
        try:
            sftp.rename(source, target)
        except Exception:
            sftp.rename(backup, target)
            raise
        sftp.remove(backup)

    def upload_file(self, local_path: str, remote_path: str,
                    progress_callback: Optional[ProgressCallback] = None,
                    cancel_event: Optional[threading.Event] = None) -> bool:
        """
        Upload file to remote server

        Args:
            local_path: Local file path
            remote_path: Remote destination path (POSIX style)
            progress_callback: Optional callback(sent_bytes, total_bytes)
            cancel_event: Set it from another thread to cancel the transfer

        Returns:
            True if upload successful, False otherwise (see last_error;
            CANCELLED when it was cancelled)
        """
        self.last_error = ""
        try:
            sftp = self._require_connection()
            if not os.path.isfile(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")

            remote_path = remote_path.replace('\\', '/')
            if remote_path.endswith('/'):
                remote_path = posixpath.join(remote_path, os.path.basename(local_path))

            self._ensure_remote_dir(posixpath.dirname(remote_path))

            file_size = os.path.getsize(local_path)
            self.logger.info(f"Uploading {local_path} to {remote_path} ({file_size} bytes)")
            temp_path = remote_path + '.part' if self.atomic_uploads else remote_path
            try:
                # confirm=True (paramiko's default) checks the remote size afterwards
                sftp.put(local_path, temp_path,
                         callback=self._progress(progress_callback, cancel_event), confirm=True)
                if self.atomic_uploads:
                    self._replace_remote(sftp, temp_path, remote_path)
            except BaseException:
                if self.atomic_uploads:
                    try:
                        sftp.remove(temp_path)
                    except Exception:
                        pass
                raise
            self.logger.info(f"Upload completed: {remote_path}")
            return True

        except TransferCancelled:
            self.last_error = CANCELLED
            self.logger.warning(f"Upload cancelled: {remote_path}")
            return False
        except Exception as e:
            self.last_error = str(e) or e.__class__.__name__
            self.logger.error(f"Upload failed: {self.last_error}")
            return False

    def download_file(self, remote_path: str, local_path: str,
                      progress_callback: Optional[ProgressCallback] = None,
                      cancel_event: Optional[threading.Event] = None) -> bool:
        """
        Download file from remote server

        Args:
            remote_path: Remote file path (POSIX style)
            local_path: Local destination path; an existing directory keeps the remote name
            progress_callback: Optional callback(received_bytes, total_bytes)
            cancel_event: Set it from another thread to cancel the transfer

        Returns:
            True if download successful, False otherwise (see last_error;
            CANCELLED when it was cancelled)
        """
        self.last_error = ""
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
            # truncated file where a good one is expected. paramiko's get()
            # raises on a size mismatch.
            partial = local_path + '.part'
            try:
                sftp.get(remote_path, partial,
                         callback=self._progress(progress_callback, cancel_event))
                os.replace(partial, local_path)
            finally:
                if os.path.exists(partial):
                    os.remove(partial)

            self.logger.info(f"Download completed: {local_path}")
            return True

        except TransferCancelled:
            self.last_error = CANCELLED
            self.logger.warning(f"Download cancelled: {remote_path}")
            return False
        except Exception as e:
            self.last_error = str(e) or e.__class__.__name__
            self.logger.error(f"Download failed: {self.last_error}")
            return False

    # ----- folders, wildcards and listings --------------------------------

    def is_remote_dir(self, remote_path: str) -> bool:
        """True when the remote path exists and is a directory"""
        try:
            attrs = self._require_connection().stat(remote_path.replace('\\', '/'))
            return attrs.st_mode is not None and stat.S_ISDIR(attrs.st_mode)
        except Exception:
            return False

    def list_dir(self, remote_path: str) -> List[RemoteEntry]:
        """
        List a remote directory with types, sizes and times

        Args:
            remote_path: Remote directory

        Returns:
            Entries, folders first, then by name (case-insensitive)

        Raises:
            OSError: When the directory cannot be listed
        """
        entries = []
        for a in self._require_connection().listdir_attr(remote_path.replace('\\', '/') or '/'):
            mode = a.st_mode or 0
            entries.append(RemoteEntry(a.filename, stat.S_ISDIR(mode), a.st_size or 0,
                                       a.st_mtime or 0, stat.S_ISLNK(mode)))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    @staticmethod
    def _safe_name(name: str) -> bool:
        """A name from a server must be a plain file name, never a path"""
        return (name not in ('', '.', '..') and '/' not in name and '\\' not in name
                and ':' not in name and '\0' not in name)

    def _walk_remote(self, root: str, rel: str, out: List[Tuple[str, str]],
                     skipped: List[Tuple[str, str]]) -> None:
        """Collect (remote_path, relative_path) for every file under root"""
        for entry in self.list_dir(root):
            remote = posixpath.join(root, entry.name)
            relative = posixpath.join(rel, entry.name)
            if not self._safe_name(entry.name):
                skipped.append((relative, "unsafe name from server, skipped"))
            elif entry.is_link:
                skipped.append((relative, "symbolic link, skipped"))
            elif entry.is_dir:
                self._walk_remote(remote, relative, out, skipped)
            else:
                out.append((remote, relative))

    def upload(self, local_spec: str, remote_dest: str,
               progress_callback: Optional[ProgressCallback] = None,
               cancel_event: Optional[threading.Event] = None,
               item_callback: Optional[Callable[[int, int, str], None]] = None) -> BulkResult:
        """
        Upload a file, a folder (recursively) or a wildcard pattern

        A single file keeps upload_file's meaning of remote_dest (a file name,
        or a folder when it ends with '/'). A folder is placed as
        <remote_dest>/<folder name>/..., and a pattern such as D:/out/*.csv
        (files only; use ** for subfolders) puts each match directly under
        remote_dest. One failed file does not stop the others. Existing remote
        files are replaced. Empty folders are not created.

        Args:
            local_spec: File, folder or pattern
            remote_dest: Remote destination
            progress_callback: callback(sent_bytes, total_bytes) per file
            cancel_event: Set from another thread to cancel
            item_callback: callback(index, count, name) before each file

        Returns:
            BulkResult; last_error holds its summary when it is not ok
        """
        self.last_error = ""
        result = BulkResult()
        local_spec = os.path.expanduser(local_spec)
        if os.path.isdir(local_spec):
            base = os.path.basename(os.path.normpath(local_spec))
            files = []
            for dirpath, _dirs, names in os.walk(local_spec):
                for name in names:
                    full = os.path.join(dirpath, name)
                    relative = os.path.relpath(full, local_spec).replace(os.sep, '/')
                    files.append((full, posixpath.join(base, relative)))
            files.sort(key=lambda f: f[1])
        elif has_wildcard(local_spec):
            matches = sorted(m for m in glob.glob(local_spec, recursive=True) if os.path.isfile(m))
            files = [(m, os.path.basename(m)) for m in matches]
        else:
            ok = self.upload_file(local_spec, remote_dest, progress_callback, cancel_event)
            result.done = 1 if ok else 0
            if not ok:
                if self.last_error == CANCELLED:
                    result.cancelled = True
                else:
                    result.failed.append((os.path.basename(local_spec), self.last_error))
            return result

        if not files:
            result.message = f"No files match {local_spec}"
            self.last_error = result.message
            return result

        dest = remote_dest.replace('\\', '/').rstrip('/') or '/'
        for index, (local_path, relative) in enumerate(files, 1):
            if cancel_event is not None and cancel_event.is_set():
                result.cancelled = True
                break
            if item_callback:
                item_callback(index, len(files), relative)
            if self.upload_file(local_path, posixpath.join(dest, relative),
                                progress_callback, cancel_event):
                result.done += 1
            elif self.last_error == CANCELLED:
                result.cancelled = True
                break
            else:
                result.failed.append((relative, self.last_error))
        self.last_error = "" if result.ok else result.summary()
        return result

    def download(self, remote_spec: str, local_dest: str,
                 progress_callback: Optional[ProgressCallback] = None,
                 cancel_event: Optional[threading.Event] = None,
                 item_callback: Optional[Callable[[int, int, str], None]] = None) -> BulkResult:
        """
        Download a file, a folder (recursively) or a wildcard pattern

        A single file keeps download_file's meaning of local_dest. A folder
        lands in <local_dest>/<folder name>/..., and a pattern such as
        /in/*.csv (files in one folder; the pattern may only be in the last
        part) puts each match under local_dest. Symbolic links and names that
        could escape the destination are skipped. Existing local files are
        replaced.

        Args:
            remote_spec: File, folder or pattern
            local_dest: Local file or folder
            progress_callback: callback(received_bytes, total_bytes) per file
            cancel_event: Set from another thread to cancel
            item_callback: callback(index, count, name) before each file

        Returns:
            BulkResult; last_error holds its summary when it is not ok
        """
        self.last_error = ""
        result = BulkResult()
        spec = remote_spec.replace('\\', '/')
        skipped: List[Tuple[str, str]] = []
        files: List[Tuple[str, str]] = []
        try:
            if has_wildcard(spec):
                parent, pattern = posixpath.split(spec)
                if has_wildcard(parent):
                    result.message = ("A pattern may only be in the last part of the path "
                                      "(for example /in/*.csv)")
                    self.last_error = result.message
                    return result
                for entry in self.list_dir(parent or '/'):
                    if fnmatch.fnmatchcase(entry.name, pattern) and not entry.is_dir:
                        if not self._safe_name(entry.name):
                            skipped.append((entry.name, "unsafe name from server, skipped"))
                        elif entry.is_link:
                            skipped.append((entry.name, "symbolic link, skipped"))
                        else:
                            files.append((posixpath.join(parent or '/', entry.name), entry.name))
            elif self.is_remote_dir(spec):
                base = posixpath.basename(spec.rstrip('/')) or 'root'
                self._walk_remote(spec, base, files, skipped)
            else:
                ok = self.download_file(spec, local_dest, progress_callback, cancel_event)
                result.done = 1 if ok else 0
                if not ok:
                    if self.last_error == CANCELLED:
                        result.cancelled = True
                    else:
                        result.failed.append((posixpath.basename(spec), self.last_error))
                return result
        except Exception as e:
            result.message = f"Could not list {spec}: {e}"
            self.last_error = result.message
            return result

        result.failed.extend(skipped)
        if not files and not skipped:
            result.message = f"No files match {remote_spec}"
            self.last_error = result.message
            return result

        for index, (remote_path, relative) in enumerate(files, 1):
            if cancel_event is not None and cancel_event.is_set():
                result.cancelled = True
                break
            if item_callback:
                item_callback(index, len(files), relative)
            target = os.path.join(local_dest, *relative.split('/'))
            if self.download_file(remote_path, target, progress_callback, cancel_event):
                result.done += 1
            elif self.last_error == CANCELLED:
                result.cancelled = True
                break
            else:
                result.failed.append((relative, self.last_error))
        self.last_error = "" if result.ok else result.summary()
        return result

    def delete_file(self, remote_path: str) -> bool:
        """
        Delete file from remote server

        Args:
            remote_path: Remote file path to delete

        Returns:
            True if deletion successful, False otherwise
        """
        self.last_error = ""
        try:
            self._require_connection().remove(remote_path.replace('\\', '/'))
            self.logger.info(f"Deleted: {remote_path}")
            return True

        except Exception as e:
            self.last_error = str(e) or e.__class__.__name__
            self.logger.error(f"Deletion failed: {self.last_error}")
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
