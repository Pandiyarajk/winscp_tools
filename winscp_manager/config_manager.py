"""
Configuration Manager for WinSCP Manager credentials and settings.

Secrets can be kept out of the file: the environment variables
WINSCP_MANAGER_PASSWORD and WINSCP_MANAGER_KEY_PASSPHRASE override the
`password` and `private_key_passphrase` keys when set.

Author: Pandiyaraj Karuppasamy
Date: Oct-19-2025
Modified: Oct-17-2026
"""

import configparser
import os
from typing import Any, Dict

PASSWORD_ENV = "WINSCP_MANAGER_PASSWORD"
PASSPHRASE_ENV = "WINSCP_MANAGER_KEY_PASSPHRASE"

HOST_KEY_POLICIES = ("accept_new", "reject", "auto_add")


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
            'known_hosts_file': os.path.expanduser(
                self.config.get('DEFAULT', 'known_hosts_file', fallback='known_hosts')
            ),
            'timeout': self.config.getfloat('DEFAULT', 'timeout', fallback=30.0),
        }

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
        }

    def get_logging_config(self) -> Dict[str, str]:
        """Get logging configuration"""
        return {
            'log_file': self.config.get('LOGGING', 'log_file', fallback='winscp_manager.log'),
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
