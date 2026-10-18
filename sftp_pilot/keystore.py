"""
Passwords and key passphrases in the operating system's keyring (Windows
Credential Manager, macOS Keychain, Secret Service on Linux).

Optional: needs `pip install sftp-pilot[keyring]`, and a server opts in with
`password_store = keyring` in its config section. Nothing here runs unless a
server asks for it, so unattended runs never wait on a keyring that is locked
or missing.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

from typing import Optional

SERVICE = "sftp-pilot"
KINDS = ("password", "passphrase")


class KeyringUnavailable(Exception):
    """The keyring package is not installed or no usable backend exists"""


def entry_name(kind: str, username: str, host: str, port: int) -> str:
    """
    Name under which a secret is stored

    Args:
        kind: 'password' or 'passphrase'
        username: Login name
        host: Server host
        port: Server port

    Returns:
        For example 'alice@host.example:22', with '#passphrase' appended for a key passphrase
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    base = f"{username}@{host}:{port}"
    return base if kind == "password" else base + "#passphrase"


def _backend():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        raise KeyringUnavailable(
            "The keyring package is not installed. Install it with: pip install sftp-pilot[keyring]"
        ) from None
    if isinstance(keyring.get_keyring(), fail.Keyring):
        raise KeyringUnavailable("No usable keyring backend on this system")
    return keyring


def get_secret(kind: str, username: str, host: str, port: int) -> Optional[str]:
    """
    Read a stored secret

    Args:
        kind: 'password' or 'passphrase'
        username: Login name
        host: Server host
        port: Server port

    Returns:
        The secret, or None when nothing is stored

    Raises:
        KeyringUnavailable: When there is no keyring to ask
    """
    keyring = _backend()
    try:
        return keyring.get_password(SERVICE, entry_name(kind, username, host, port))
    except Exception as e:  # a locked or broken backend must not look like "no secret"
        raise KeyringUnavailable(f"The keyring could not be read: {e}") from e


def set_secret(kind: str, username: str, host: str, port: int, secret: str) -> None:
    """
    Store a secret, replacing an existing one

    Raises:
        KeyringUnavailable: When there is no keyring to write to
    """
    keyring = _backend()
    try:
        keyring.set_password(SERVICE, entry_name(kind, username, host, port), secret)
    except Exception as e:
        raise KeyringUnavailable(f"The keyring could not be written: {e}") from e


def delete_secret(kind: str, username: str, host: str, port: int) -> bool:
    """
    Remove a stored secret

    Returns:
        True when something was removed, False when nothing was stored

    Raises:
        KeyringUnavailable: When there is no keyring to ask
    """
    keyring = _backend()
    from keyring.errors import PasswordDeleteError
    try:
        keyring.delete_password(SERVICE, entry_name(kind, username, host, port))
        return True
    except PasswordDeleteError:
        return False
    except Exception as e:
        raise KeyringUnavailable(f"The keyring could not be changed: {e}") from e
