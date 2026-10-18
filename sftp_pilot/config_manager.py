"""
Configuration Manager for SFTP Pilot credentials and settings.

The [DEFAULT] section is the default server. More servers are `[server:<name>]`
sections. A named server never inherits credentials: host, port, username,
password, key path and passphrase must be written in its own section, so a
server that only changes the host can not receive another server's password.
Only non-secret settings (protocol, host_key_policy, known_hosts_file, timeout,
atomic_uploads) fall back to [DEFAULT].

Secrets can be kept out of the file. For the default server the environment
variables SFTP_PILOT_PASSWORD and SFTP_PILOT_KEY_PASSPHRASE override
`password` and `private_key_passphrase`; for `[server:prod]` the variables are
SFTP_PILOT_PASSWORD_PROD and SFTP_PILOT_KEY_PASSPHRASE_PROD. A variable meant
for one server is never used for another.

A server can also keep them in the OS keyring: `password_store = keyring`
(opt-in per server; never inherited). The order is then: environment variable,
keyring entry, value in the file.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import configparser
import os
import re
from typing import Any, Dict, List

PASSWORD_ENV = "SFTP_PILOT_PASSWORD"
PASSPHRASE_ENV = "SFTP_PILOT_KEY_PASSPHRASE"

HOST_KEY_POLICIES = ("accept_new", "ask", "reject", "auto_add")
PASSWORD_STORES = ("file", "keyring")

DEFAULT_SERVER = "default"
SERVER_PREFIX = "server:"
# Keys a named server may take from [DEFAULT]. Credentials and the address are not here.
INHERITED = ("protocol", "host_key_policy", "known_hosts_file", "timeout", "atomic_uploads")


def env_suffix(server: str) -> str:
    """
    Environment variable suffix for a server name

    Args:
        server: Server name ('' or 'default' for the default server)

    Returns:
        '' for the default server, otherwise '_<NAME>' with non-alphanumerics as '_'
    """
    if not server or server == DEFAULT_SERVER:
        return ""
    return "_" + re.sub(r"[^A-Z0-9]", "_", server.upper())


class ConfigManager:
    """Manages configuration file reading and validation"""

    def __init__(self, config_path: str = "config.ini"):
        """
        Initialize the configuration manager

        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        # No section is the special "defaults for every section" one: [DEFAULT]
        # is an ordinary section here, so nothing is inherited by accident.
        self.config = configparser.ConfigParser(default_section="__sftp_pilot_no_defaults__")
        self.load_config()

    def load_config(self) -> None:
        """
        Load configuration from file

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If a section name is not allowed
        """
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        self.config.read(self.config_path, encoding="utf-8")
        if self.config.has_section(SERVER_PREFIX + DEFAULT_SERVER):
            raise ValueError(f"[{SERVER_PREFIX}{DEFAULT_SERVER}] is not allowed: "
                             f"the [DEFAULT] section is the default server")

    # ----- servers ------------------------------------------------------------

    def server_names(self) -> List[str]:
        """
        Names of the configured servers, in file order

        Returns:
            'default' first when [DEFAULT] describes a server, then each [server:<name>]
        """
        names = []
        if self.config.has_section("DEFAULT") and self.config.has_option("DEFAULT", "host"):
            names.append(DEFAULT_SERVER)
        names += [s[len(SERVER_PREFIX):] for s in self.config.sections()
                  if s.startswith(SERVER_PREFIX) and len(s) > len(SERVER_PREFIX)]
        return names

    def _section_for(self, server: str) -> str:
        """Section name for a server, or ValueError listing the choices"""
        name = (server or "").strip() or DEFAULT_SERVER
        names = self.server_names()
        if name == DEFAULT_SERVER:
            if DEFAULT_SERVER in names:
                return "DEFAULT"
            if names:
                raise ValueError(f"The config has no default server ([DEFAULT] with a host). "
                                 f"Choose one of: {', '.join(names)}")
            raise ValueError("The config describes no server: add host and username to [DEFAULT]")
        if name not in names:
            raise ValueError(f"Unknown server '{name}'. Configured servers: {', '.join(names) or 'none'}")
        return SERVER_PREFIX + name

    def _opt(self, section: str, key: str, fallback: str = "") -> str:
        """An option from its own section, or for INHERITED keys from [DEFAULT]"""
        if self.config.has_option(section, key):
            return self.config.get(section, key)
        if section != "DEFAULT" and key in INHERITED and self.config.has_option("DEFAULT", key):
            return self.config.get("DEFAULT", key)
        return fallback

    def _typed(self, section: str, key: str, fallback: Any, convert) -> Any:
        raw = self._opt(section, key, "").strip()
        if not raw:
            return fallback
        try:
            return convert(raw)
        except ValueError:
            raise ValueError(f"[{section}] {key} = {raw!r} is not valid") from None

    @staticmethod
    def _bool(raw: str) -> bool:
        states = configparser.ConfigParser.BOOLEAN_STATES
        if raw.lower() not in states:
            raise ValueError(raw)
        return states[raw.lower()]

    def identity(self, server: str = "") -> Dict[str, Any]:
        """
        Who and where a server is, without reading any secret

        Args:
            server: Server name; '' or 'default' for the [DEFAULT] server

        Returns:
            Dictionary with server, section, host, port and username

        Raises:
            ValueError: If the server is unknown or lacks host or username
        """
        section = self._section_for(server)
        name = DEFAULT_SERVER if section == "DEFAULT" else section[len(SERVER_PREFIX):]
        for required in ('host', 'username'):
            if not self.config.has_option(section, required):
                raise ValueError(f"[{section}] needs '{required}'")
        return {
            'server': name,
            'section': section,
            'host': self.config.get(section, 'host'),
            'port': self._typed(section, 'port', 22, int),
            'username': self.config.get(section, 'username'),
        }

    def _stored_secret(self, kind: str, who: Dict[str, Any]) -> str:
        """Value from the keyring for a server that uses password_store = keyring ('' if none)"""
        from . import keystore
        try:
            found = keystore.get_secret(kind, who['username'], who['host'], who['port'])
        except keystore.KeyringUnavailable as e:
            raise ValueError(f"[{who['section']}] uses password_store = keyring, but {e}") from None
        return found or ''

    def get_connection_details(self, server: str = "") -> Dict[str, Any]:
        """
        Get connection details for a server, with secrets taken from the
        environment, then the keyring (when the server opts in), then the file.

        Args:
            server: Server name; '' or 'default' for the [DEFAULT] server

        Returns:
            Dictionary containing connection parameters (including 'server')

        Raises:
            ValueError: If the server is unknown or a setting is unsupported
        """
        who = self.identity(server)
        section, name = who['section'], who['server']

        protocol = self._opt(section, 'protocol', 'sftp').strip().lower()
        if protocol != 'sftp':
            raise ValueError(f"Unsupported protocol '{protocol}': only 'sftp' is supported")

        policy = self._opt(section, 'host_key_policy', 'accept_new').strip().lower()
        if policy not in HOST_KEY_POLICIES:
            raise ValueError(
                f"Unsupported host_key_policy '{policy}': use one of {', '.join(HOST_KEY_POLICIES)}"
            )

        store = self.config.get(section, 'password_store', fallback='file').strip().lower()
        if store not in PASSWORD_STORES:
            raise ValueError(f"[{section}] password_store = {store!r}: use one of {', '.join(PASSWORD_STORES)}")

        suffix = env_suffix(name)
        key_path = os.path.expanduser(self.config.get(section, 'private_key_path', fallback=''))
        password = os.environ.get(PASSWORD_ENV + suffix, '')
        passphrase = os.environ.get(PASSPHRASE_ENV + suffix, '')
        if store == 'keyring':
            password = password or self._stored_secret('password', who)
            passphrase = passphrase or self._stored_secret('passphrase', who)
            if not password and not key_path:
                flag = '' if name == DEFAULT_SERVER else f' --server {name}'
                raise ValueError(f"[{section}] uses password_store = keyring but no password is stored "
                                 f"for {who['username']}@{who['host']}:{who['port']}. "
                                 f"Run: sftp-pilot --store-password{flag}")
        return {
            'server': name,
            'protocol': protocol,
            'host': who['host'],
            'port': who['port'],
            'username': who['username'],
            'password': password or self.config.get(section, 'password', fallback=''),
            'private_key_path': key_path,
            'private_key_passphrase': passphrase or self.config.get(section, 'private_key_passphrase', fallback=''),
            'host_key_policy': policy,
            'known_hosts_file': self.resolve(self._opt(section, 'known_hosts_file', 'known_hosts')),
            'timeout': self._typed(section, 'timeout', 30.0, float),
            'atomic_uploads': self._typed(section, 'atomic_uploads', True, self._bool),
        }

    def resolve(self, path: str) -> str:
        """
        Resolve a path from the config against the config file's folder, so it
        does not depend on the working directory (Task Scheduler starts in
        System32, cron in the home folder).

        Args:
            path: Path as written in the config ('' stays '')

        Returns:
            An absolute path, or '' for an empty value
        """
        if not path:
            return ''
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return path
        return os.path.join(os.path.dirname(os.path.abspath(self.config_path)), path)

    def get_paths(self) -> Dict[str, str]:
        """Get path configurations"""
        return {
            'remote_upload_dir': self.config.get('PATHS', 'remote_upload_dir', fallback='/'),
            'local_download_dir': self.config.get('PATHS', 'local_download_dir', fallback='./downloads'),
        }

    def get_scheduling_config(self) -> Dict[str, Any]:
        """Get scheduling configuration"""
        return {
            'enabled': self.config.getboolean('SCHEDULING', 'enabled', fallback=True),
            'check_interval': max(1, self.config.getint('SCHEDULING', 'check_interval', fallback=60)),
            'retries': max(0, self.config.getint('SCHEDULING', 'retries', fallback=3)),
            'retry_delay': max(1, self.config.getint('SCHEDULING', 'retry_delay', fallback=60)),
        }

    def get_logging_config(self) -> Dict[str, str]:
        """Get logging configuration"""
        return {
            'log_file': self.resolve(self.config.get('LOGGING', 'log_file', fallback='sftp_pilot.log')),
            'log_level': self.config.get('LOGGING', 'log_level', fallback='INFO').upper(),
        }

    def update_config(self, section: str, key: str, value: str) -> None:
        """
        Update configuration value

        Args:
            section: Configuration section
            key: Configuration key
            value: New value
        """
        if not self.config.has_section(section):
            self.config.add_section(section)

        self.config.set(section, key, value)

        with open(self.config_path, 'w', encoding="utf-8") as configfile:
            self.config.write(configfile)
