"""
Configuration Manager for SFTP Pilot credentials and settings.

Secrets can be kept out of the file: the environment variables
SFTP_PILOT_PASSWORD and SFTP_PILOT_KEY_PASSPHRASE override the
`password` and `private_key_passphrase` keys when set.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-18-2026
"""

import configparser
import os
from typing import Any, Dict

PASSWORD_ENV = "SFTP_PILOT_PASSWORD"
PASSPHRASE_ENV = "SFTP_PILOT_KEY_PASSPHRASE"

HOST_KEY_POLICIES = ("accept_new", "ask", "reject", "auto_add")


class ConfigManager:
    """Manages configuration file reading and validation"""

    def __init__(self, config_path: str = "config.ini"):
        """
        Initialize the configuration manager

        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from file"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        self.config.read(self.config_path, encoding="utf-8")

    def get_connection_details(self) -> Dict[str, Any]:
        """
        Get connection details from config, with secrets taken from the
        environment when the matching variable is set.

        Returns:
            Dictionary containing connection parameters

        Raises:
            ValueError: If a setting has an unsupported value
        """
        protocol = self.config.get('DEFAULT', 'protocol', fallback='sftp').strip().lower()
        if protocol != 'sftp':
            raise ValueError(f"Unsupported protocol '{protocol}': only 'sftp' is supported")

        policy = self.config.get('DEFAULT', 'host_key_policy', fallback='accept_new').strip().lower()
        if policy not in HOST_KEY_POLICIES:
            raise ValueError(
                f"Unsupported host_key_policy '{policy}': use one of {', '.join(HOST_KEY_POLICIES)}"
            )

        return {
            'protocol': protocol,
            'host': self.config.get('DEFAULT', 'host'),
            'port': self.config.getint('DEFAULT', 'port', fallback=22),
            'username': self.config.get('DEFAULT', 'username'),
            'password': os.environ.get(PASSWORD_ENV)
            or self.config.get('DEFAULT', 'password', fallback=''),
            'private_key_path': os.path.expanduser(
                self.config.get('DEFAULT', 'private_key_path', fallback='')
            ),
            'private_key_passphrase': os.environ.get(PASSPHRASE_ENV)
            or self.config.get('DEFAULT', 'private_key_passphrase', fallback=''),
            'host_key_policy': policy,
            'known_hosts_file': self.resolve(
                self.config.get('DEFAULT', 'known_hosts_file', fallback='known_hosts')
            ),
            'timeout': self.config.getfloat('DEFAULT', 'timeout', fallback=30.0),
            'atomic_uploads': self.config.getboolean('DEFAULT', 'atomic_uploads', fallback=True),
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
        if section != 'DEFAULT' and section not in self.config:
            self.config.add_section(section)

        self.config.set(section, key, value)

        with open(self.config_path, 'w', encoding="utf-8") as configfile:
            self.config.write(configfile)
