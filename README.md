# WinSCP Manager

A comprehensive Python application for managing WinSCP/SFTP file operations with advanced scheduling capabilities and dual interfaces (GUI and Console).

**Repository:** [https://github.com/Pandiyarajk/winscp_tools.git](https://github.com/Pandiyarajk/winscp_tools.git)  
**Author:** Pandiyaraj Karuppasamy  
**Version:** 1.0.0  
**License:** MIT

## Features

### Core Functionality
- ✅ **WinSCP/SFTP Protocol Support** - Secure file transfer using SFTP protocol
- ✅ **Configuration Management** - Easy credential management via config file
- ✅ **Large File Support** - Upload and download large files with progress tracking
- ✅ **File Operations**
  - Upload files to remote server
  - Download files from remote server
  - Delete files on remote server
  - List remote directory contents

### Scheduling System
- ✅ **Task Scheduler** - Automated task execution
- ✅ **Recurring Tasks** - Schedule tasks to run at intervals
- ✅ **Task Management** - Add, view, and remove scheduled tasks
- ✅ **Persistent Storage** - Tasks are saved and restored between sessions
- ✅ **Multiple Task Types** - Upload, download, and delete operations

### User Interfaces
- ✅ **GUI Interface** - Beautiful tkinter-based GUI with tabs
  - Connection management
  - File operations with progress bars
  - Scheduler with task list view
  - Real-time logging
- ✅ **Console Interface** - Full-featured command-line interface
  - Interactive menu system
  - All file operations supported
  - Scheduler management

### Cross-Platform Support
- ✅ **Windows Support** - Full compatibility with Windows OS
- ✅ **Linux/Mac Support** - Works on Unix-based systems
- ✅ **Python 3.7+** - Modern Python support

## Quick Start

Get up and running in 3 easy steps:

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Your Connection
Edit `config.ini` with your server details:
```ini
[DEFAULT]
protocol = sftp
host = your-server.com
port = 22
username = your_username
password = your_password
```

**Security Tip:** For production, use key-based authentication by setting `private_key_path` instead of password.

### Step 3: Run the Application
```bash
# GUI Interface (Default)
python main.py

# Console Interface
python main.py --console
```

That's it! You're ready to transfer files and schedule tasks.

## Installation

### Requirements
- Python 3.7 or higher
- pip (Python package installer)

### Setup

#### Option 1: Standard Installation (Recommended)

1. **Clone the repository**
```bash
git clone https://github.com/Pandiyarajk/winscp_tools.git
cd winscp_tools
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

#### Option 2: Development Installation

For developers who want to contribute:

```bash
# Clone the repository
git clone https://github.com/Pandiyarajk/winscp_tools.git
cd winscp_tools

# Install with development dependencies
pip install -r requirements-dev.txt

# Install in editable mode
pip install -e .
```

#### Option 3: Package Installation

Install as a Python package:

```bash
pip install git+https://github.com/Pandiyarajk/winscp_tools.git
```

3. **Configure connection settings**

Edit the `config.ini` file with your server details:

```ini
[DEFAULT]
protocol = sftp
host = your-server.com
port = 22
username = your_username
password = your_password

[PATHS]
remote_upload_dir = /remote/upload/path
local_download_dir = ./downloads
temp_dir = ./temp

[SCHEDULING]
enabled = true
check_interval = 60

[LOGGING]
log_file = winscp_manager.log
log_level = INFO
```

## Usage

### GUI Interface (Default)

Run the application with the GUI interface:

```bash
python main.py
```

or explicitly:

```bash
python main.py --gui
```

#### GUI Features:

1. **Connection Tab**
   - Configure server connection settings
   - Connect/disconnect from server
   - Load configuration from file

2. **File Operations Tab**
   - Upload files with progress bar
   - Download files with progress tracking
   - Delete remote files
   - Browse local and remote paths

3. **Scheduler Tab**
   - Add scheduled tasks (upload, download, delete)
   - Configure recurring tasks with intervals
   - View all scheduled tasks
   - Remove tasks
   - Start/stop scheduler

4. **Logs Tab**
   - Real-time logging output
   - Track all operations and errors

### Console Interface

Run the application with the console interface:

```bash
python main.py --console
```

#### Console Menu Options:

```
1. Connect to server
2. Disconnect from server
3. Upload file
4. Download file
5. Delete file
6. List remote files
7. Schedule task
8. View scheduled tasks
9. Remove scheduled task
10. Start scheduler
11. Stop scheduler
12. Exit
```

## Configuration

### Connection Settings

The application supports two authentication methods:

1. **Password Authentication** (default)
```ini
username = myuser
password = mypassword
```

2. **Key-Based Authentication**
```ini
username = myuser
private_key_path = /path/to/private/key
```

### Paths Configuration

Customize default paths for uploads and downloads:

```ini
[PATHS]
remote_upload_dir = /remote/upload/path
local_download_dir = ./downloads
temp_dir = ./temp
```

### Scheduler Configuration

Configure the scheduler behavior:

```ini
[SCHEDULING]
enabled = true
check_interval = 60  # Check for tasks every 60 seconds
```

### Logging Configuration

Customize logging output:

```ini
[LOGGING]
log_file = winscp_manager.log
log_level = INFO  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Scheduling Tasks

### GUI Scheduler

1. Navigate to the **Scheduler** tab
2. Select task type (Upload, Download, or Delete)
3. Specify source and destination paths
4. Set when to run (in minutes from now)
5. Optionally enable recurring execution
6. Click **Add Task**
7. Click **Start Scheduler** to begin task execution

### Console Scheduler

1. Select option **7. Schedule task** from the menu
2. Choose task type
3. Enter source path
4. Enter destination path (if applicable)
5. Specify delay in minutes
6. Configure recurring settings if needed
7. Start scheduler with option **10**

### Task Types

- **Upload**: Transfer file from local to remote server
- **Download**: Transfer file from remote server to local
- **Delete**: Remove file from remote server

## Examples

### Example 1: Upload a Large File

**GUI:**
1. Connect to server in Connection tab
2. Go to File Operations tab
3. Browse and select local file
4. Enter remote destination path
5. Click Upload
6. Monitor progress bar

**Console:**
```
1. Connect to server
3. Upload file
   Local file: /home/user/largefile.zip
   Remote path: /backups/largefile.zip
```

### Example 2: Schedule Daily Backup

**GUI:**
1. Go to Scheduler tab
2. Select "Upload" task type
3. Source: /home/user/backup.zip
4. Destination: /server/backups/backup.zip
5. Run in: 5 minutes
6. Check "Recurring Task"
7. Interval: 1440 minutes (24 hours)
8. Add Task
9. Start Scheduler

**Console:**
```
7. Schedule task
   Task type: 1 (Upload)
   Source: /home/user/backup.zip
   Destination: /server/backups/backup.zip
   Run in minutes: 5
   Recurring: yes
   Interval: 1440
10. Start scheduler
```

### Example 3: Automated File Cleanup

Schedule recurring deletion of old files:

1. Create delete task
2. Source: /server/temp/old_file.log
3. Recurring: Yes
4. Interval: 60 minutes

## Project Structure

```
winscp_tools/
├── winscp_manager/           # Main package directory
│   ├── __init__.py           # Package initialization
│   ├── config_manager.py     # Configuration handling
│   ├── winscp_handler.py     # SFTP operations
│   ├── scheduler.py          # Task scheduling
│   ├── gui.py                # GUI interface
│   └── console.py            # Console interface
├── main.py                   # Application entry point
├── setup.py                  # Package setup configuration
├── MANIFEST.in               # Package manifest
├── config.ini                # Configuration file (not in repo)
├── example_config.ini        # Example configuration
├── requirements.txt          # Production dependencies
├── requirements-dev.txt      # Development dependencies
├── README.md                 # Documentation
├── CHANGE_LOG.md             # Version history
├── LICENSE                   # MIT License
└── .gitignore                # Git ignore rules
```

## Troubleshooting

### Connection Issues

**Problem:** Cannot connect to server
- Check host and port settings
- Verify username and password
- Ensure firewall allows SFTP connections
- Check if SSH/SFTP is enabled on server

### Authentication Issues

**Problem:** Authentication failed
- Verify credentials in config.ini
- For key-based auth, check private key path and permissions
- Ensure the user has appropriate permissions on server

### Scheduler Not Working

**Problem:** Scheduled tasks not executing
- Verify scheduler is started
- Check task status in task list
- Ensure connection credentials are correct
- Review logs for error messages

### GUI Not Starting

**Problem:** GUI fails to launch
- Verify tkinter is installed: `python -m tkinter`
- On Linux, install tkinter: `sudo apt-get install python3-tk`
- Try console interface as alternative: `python main.py --console`

## Security Considerations

- Store `config.ini` securely with appropriate file permissions
- Use key-based authentication when possible
- Never commit `config.ini` with real credentials to version control
- Consider using environment variables for sensitive data
- Regularly update dependencies for security patches

## Dependencies

- **paramiko** - SSH/SFTP protocol implementation
- **cryptography** - Cryptographic operations
- **tkinter** - GUI framework (included with Python)

See `requirements.txt` for complete list with versions.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests on [GitHub](https://github.com/Pandiyarajk/winscp_tools.git).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues, questions, or contributions:
- Open an issue on [GitHub](https://github.com/Pandiyarajk/winscp_tools/issues)
- Contact: Pandiyaraj Karuppasamy

## Version Information

**Current Version:** 1.0.0  
**Last Updated:** October 19, 2025  
**Python:** 3.7+

See [CHANGE_LOG.md](CHANGE_LOG.md) for complete version history and changes.

---

<div align="center">

**Made with ❤️ for secure and automated file transfers**

[GitHub](https://github.com/Pandiyarajk/winscp_tools) • [Report Bug](https://github.com/Pandiyarajk/winscp_tools/issues) • [Request Feature](https://github.com/Pandiyarajk/winscp_tools/issues)

Copyright © 2025 [Pandiyaraj Karuppasamy](https://github.com/Pandiyarajk)

</div>
