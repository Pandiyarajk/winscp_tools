"""
Configuration Manager for WinSCP credentials and settings
"""

import configparser
import os
from typing import Dict, Optional


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
        
        self.config.read(self.config_path)
    
    def get_connection_details(self) -> Dict[str, str]:
        """
        Get WinSCP connection details from config
        
        Returns:
            Dictionary containing connection parameters
        """
        return {
            'protocol': self.config.get('DEFAULT', 'protocol', fallback='sftp'),
            'host': self.config.get('DEFAULT', 'host'),
            'port': self.config.getint('DEFAULT', 'port', fallback=22),
            'username': self.config.get('DEFAULT', 'username'),
            'password': self.config.get('DEFAULT', 'password', fallback=''),
            'private_key_path': self.config.get('DEFAULT', 'private_key_path', fallback='')
        }
    
    def get_paths(self) -> Dict[str, str]:
        """Get path configurations"""
        return {
            'remote_upload_dir': self.config.get('PATHS', 'remote_upload_dir', fallback='/'),
            'local_download_dir': self.config.get('PATHS', 'local_download_dir', fallback='./downloads'),
            'temp_dir': self.config.get('PATHS', 'temp_dir', fallback='./temp')
        }
    
    def get_scheduling_config(self) -> Dict:
        """Get scheduling configuration"""
        return {
            'enabled': self.config.getboolean('SCHEDULING', 'enabled', fallback=True),
            'check_interval': self.config.getint('SCHEDULING', 'check_interval', fallback=60)
        }
    
    def get_logging_config(self) -> Dict[str, str]:
        """Get logging configuration"""
        return {
            'log_file': self.config.get('LOGGING', 'log_file', fallback='winscp_manager.log'),
            'log_level': self.config.get('LOGGING', 'log_level', fallback='INFO')
        }
    
    def update_config(self, section: str, key: str, value: str) -> None:
        """
        Update configuration value
        
        Args:
            section: Configuration section
            key: Configuration key
            value: New value
        """
        if section not in self.config:
            self.config.add_section(section)
        
        self.config.set(section, key, value)
        
        with open(self.config_path, 'w') as configfile:
            self.config.write(configfile)
