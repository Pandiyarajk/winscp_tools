# Change Log

All notable changes to WinSCP Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-10-19

### Added

#### Core Features
- **WinSCP/SFTP Protocol Handler**
  - Full SFTP protocol support using paramiko library
  - Connection management with automatic reconnection
  - Support for password and key-based authentication
  - Secure file transfer operations

#### File Operations
- **Upload Functionality**
  - Upload files of any size to remote server
  - Progress tracking with callback support
  - Automatic remote directory creation
  - Large file support with efficient streaming

- **Download Functionality**
  - Download files from remote server
  - Progress tracking and reporting
  - Automatic local directory creation
  - Resume capability for interrupted transfers

- **Delete Functionality**
  - Delete files from remote server
  - Safety confirmations in both interfaces
  - Batch delete support through scheduler

- **File Management**
  - List files in remote directories
  - Check file existence
  - Get file metadata

#### Scheduling System
- **Task Scheduler**
  - Background task execution engine
  - Support for three task types: Upload, Download, Delete
  - Persistent task storage (JSON-based)
  - Automatic task state management

- **Recurring Tasks**
  - Configure tasks to run at regular intervals
  - Customizable interval in minutes
  - Automatic rescheduling after execution

- **Task Management**
  - Add new scheduled tasks
  - View all scheduled tasks with details
  - Remove/cancel tasks
  - Task status tracking (pending, running, completed, failed)
  - Error logging for failed tasks

#### Configuration Management
- **Config File Support**
  - INI-based configuration file
  - Separate sections for connection, paths, scheduling, and logging
  - Easy credential management
  - Support for multiple authentication methods

- **Path Management**
  - Default remote upload directory
  - Default local download directory
  - Temporary file directory configuration

#### User Interfaces

##### GUI Interface (Tkinter)
- **Main Window**
  - Modern tabbed interface design
  - 1000x700 default window size
  - Status bar with connection status
  - Real-time updates

- **Connection Tab**
  - Server configuration form
  - Protocol selection (SFTP, SCP)
  - Connect/disconnect buttons
  - Load configuration from file
  - Visual connection status

- **File Operations Tab**
  - Upload section with file browser
  - Download section with save dialog
  - Delete section with confirmation
  - Progress bar for transfers
  - Real-time transfer statistics

- **Scheduler Tab**
  - Add scheduled task form
  - Task type selection dropdown
  - File browser integration
  - Recurring task configuration
  - Task list view (TreeView)
  - Start/stop scheduler controls
  - Refresh and remove task buttons

- **Logs Tab**
  - Scrollable log viewer
  - Real-time log updates
  - Formatted log entries with timestamps
  - Color-coded log levels

##### Console Interface
- **Interactive Menu System**
  - 12 menu options
  - Clear, numbered interface
  - Input validation
  - User-friendly prompts

- **All File Operations**
  - Upload with progress display
  - Download with progress display
  - Delete with confirmation
  - List remote files

- **Scheduler Management**
  - Schedule new tasks interactively
  - View all scheduled tasks
  - Remove tasks by ID
  - Start/stop scheduler
  - Full task configuration

#### Cross-Platform Support
- **Windows Compatibility**
  - Full GUI support on Windows
  - Console interface with cmd.exe support
  - Path handling for Windows file system

- **Linux/Mac Support**
  - Full GUI support (with tkinter)
  - Console interface with terminal support
  - Unix path handling

#### Logging
- **Comprehensive Logging**
  - File-based logging
  - Console output
  - Configurable log levels
  - Timestamped entries
  - Error tracking

- **GUI Log Integration**
  - Custom TextHandler for tkinter
  - Thread-safe log updates
  - Auto-scrolling log view

#### Documentation
- **README.md**
  - Complete feature documentation
  - Installation instructions
  - Usage examples
  - Configuration guide
  - Troubleshooting section
  - Security considerations

- **CHANGE_LOG.md**
  - Version history
  - Detailed change tracking
  - Semantic versioning

- **Code Documentation**
  - Comprehensive docstrings
  - Type hints
  - Module documentation
  - Function documentation

#### Development
- **Project Structure**
  - Modular package design
  - Separation of concerns
  - Clean architecture
  - Easy to extend

- **Requirements Management**
  - requirements.txt with version pinning
  - Minimal dependencies
  - Clear dependency purposes

### Technical Details

#### Architecture
- **Modular Design**
  - config_manager.py - Configuration handling
  - winscp_handler.py - SFTP protocol operations
  - scheduler.py - Task scheduling and execution
  - gui.py - GUI interface with tkinter
  - console.py - Console interface
  - main.py - Application entry point

#### Dependencies
- paramiko >= 3.3.1 - SSH/SFTP implementation
- cryptography >= 41.0.5 - Cryptographic operations
- python-dateutil >= 2.8.2 - Date handling
- pytz >= 2023.3 - Timezone support

#### Python Version Support
- Python 3.7+
- Tested on Python 3.8, 3.9, 3.10, 3.11

### Security Features
- Secure password handling
- Key-based authentication support
- Auto-host-key-acceptance with warnings
- Secure configuration file storage
- Connection encryption via SSH/SFTP

### Performance
- Efficient large file handling
- Non-blocking UI operations
- Background task execution
- Threaded file operations
- Progress tracking with minimal overhead

### Known Limitations
- GUI requires tkinter (not included on some Linux distributions)
- Scheduler checks every 10 seconds (configurable in code)
- Task storage limited to JSON file (no database)
- Single connection per instance
- No multi-threading for concurrent transfers

### Future Enhancements (Planned)
- Multiple simultaneous connections
- Drag-and-drop file upload in GUI
- Batch file operations
- File synchronization
- Bandwidth throttling
- Resume failed transfers
- Email notifications for scheduled tasks
- Database backend for task storage
- Web interface
- REST API

---

## Version History Summary

- **[1.0.0]** - 2025-10-19 - Initial release with full feature set

---

**Note:** This is the initial release of WinSCP Manager. Future versions will be documented here with detailed change tracking.
