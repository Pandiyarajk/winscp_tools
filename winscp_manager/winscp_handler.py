"""
WinSCP Protocol Handler for file operations
"""

import os
import logging
from typing import Optional, List, Callable
from pathlib import Path
import paramiko
from stat import S_ISDIR


class WinSCPHandler:
    """Handles WinSCP/SFTP protocol operations"""
    
    def __init__(self, host: str, port: int, username: str, 
                 password: str = '', private_key_path: str = '', protocol: str = 'sftp'):
        """
        Initialize WinSCP handler
        
        Args:
            host: Server hostname or IP
            port: Connection port
            username: Username for authentication
            password: Password for authentication (optional if using key)
            private_key_path: Path to private key file (optional)
            protocol: Protocol to use (sftp, scp)
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key_path = private_key_path
        self.protocol = protocol
        
        self.ssh_client = None
        self.sftp_client = None
        self.logger = logging.getLogger(__name__)
    
    def connect(self) -> bool:
        """
        Establish connection to remote server
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect with key or password
            if self.private_key_path and os.path.exists(self.private_key_path):
                private_key = paramiko.RSAKey.from_private_key_file(self.private_key_path)
                self.ssh_client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    pkey=private_key
                )
            else:
                self.ssh_client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password
                )
            
            self.sftp_client = self.ssh_client.open_sftp()
            self.logger.info(f"Connected to {self.host}:{self.port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection failed: {str(e)}")
            return False
    
    def disconnect(self) -> None:
        """Close connection to remote server"""
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
        self.logger.info("Disconnected from server")
    
    def upload_file(self, local_path: str, remote_path: str, 
                   progress_callback: Optional[Callable] = None) -> bool:
        """
        Upload file to remote server
        
        Args:
            local_path: Local file path
            remote_path: Remote destination path
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if upload successful, False otherwise
        """
        try:
            if not os.path.exists(local_path):
                self.logger.error(f"Local file not found: {local_path}")
                return False
            
            # Ensure remote directory exists
            remote_dir = os.path.dirname(remote_path)
            self._ensure_remote_dir(remote_dir)
            
            file_size = os.path.getsize(local_path)
            self.logger.info(f"Uploading {local_path} to {remote_path} ({file_size} bytes)")
            
            if progress_callback:
                transferred = [0]
                
                def callback(sent, total):
                    transferred[0] = sent
                    progress_callback(sent, total)
                
                self.sftp_client.put(local_path, remote_path, callback=callback)
            else:
                self.sftp_client.put(local_path, remote_path)
            
            self.logger.info(f"Upload completed: {remote_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Upload failed: {str(e)}")
            return False
    
    def download_file(self, remote_path: str, local_path: str,
                     progress_callback: Optional[Callable] = None) -> bool:
        """
        Download file from remote server
        
        Args:
            remote_path: Remote file path
            local_path: Local destination path
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if download successful, False otherwise
        """
        try:
            # Ensure local directory exists
            local_dir = os.path.dirname(local_path)
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)
            
            self.logger.info(f"Downloading {remote_path} to {local_path}")
            
            if progress_callback:
                def callback(received, total):
                    progress_callback(received, total)
                
                self.sftp_client.get(remote_path, local_path, callback=callback)
            else:
                self.sftp_client.get(remote_path, local_path)
            
            self.logger.info(f"Download completed: {local_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Download failed: {str(e)}")
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
            self.sftp_client.remove(remote_path)
            self.logger.info(f"Deleted: {remote_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Deletion failed: {str(e)}")
            return False
    
    def list_files(self, remote_path: str) -> List[str]:
        """
        List files in remote directory
        
        Args:
            remote_path: Remote directory path
            
        Returns:
            List of file names
        """
        try:
            files = self.sftp_client.listdir(remote_path)
            return files
        except Exception as e:
            self.logger.error(f"Failed to list files: {str(e)}")
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
            self.sftp_client.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            self.logger.error(f"Error checking file existence: {str(e)}")
            return False
    
    def _ensure_remote_dir(self, remote_dir: str) -> None:
        """
        Ensure remote directory exists, create if not
        
        Args:
            remote_dir: Remote directory path
        """
        if not remote_dir or remote_dir == '/':
            return
        
        try:
            self.sftp_client.stat(remote_dir)
        except FileNotFoundError:
            # Directory doesn't exist, create it
            parent_dir = os.path.dirname(remote_dir)
            if parent_dir:
                self._ensure_remote_dir(parent_dir)
            self.sftp_client.mkdir(remote_dir)
            self.logger.info(f"Created remote directory: {remote_dir}")
