# Quick Start Guide

Get up and running with WinSCP Manager in just a few minutes!

## Installation (3 steps)

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `paramiko` - For SFTP/SSH connections
- `cryptography` - For secure communications

### Step 2: Configure Your Connection

Edit `config.ini` with your server details:

```ini
[DEFAULT]
protocol = sftp
host = your-server.com          # ← Your server address
port = 22                        # ← SSH/SFTP port (usually 22)
username = your_username         # ← Your username
password = your_password         # ← Your password
```

**Security Tip:** For production, use key-based authentication:
```ini
username = your_username
private_key_path = /path/to/your/private/key
# Leave password empty when using key
password = 
```

### Step 3: Run the Application

**GUI Interface (Default):**
```bash
python main.py
```

**Console Interface:**
```bash
python main.py --console
```

## First Steps

### Using the GUI

1. **Connect to Server**
   - Open the "Connection" tab
   - Verify your settings (loaded from config.ini)
   - Click "Connect"
   - Wait for "Connected successfully!" message

2. **Upload Your First File**
   - Go to "File Operations" tab
   - Click "Browse" next to "Local File"
   - Select a file
   - Enter remote path (e.g., `/home/user/uploaded_file.txt`)
   - Click "Upload"
   - Watch the progress bar!

3. **Schedule Your First Task**
   - Go to "Scheduler" tab
   - Select task type (Upload/Download/Delete)
   - Fill in paths
   - Set "Run in" minutes (e.g., 1 minute for testing)
   - Click "Add Task"
   - Click "Start Scheduler"
   - Watch the "Logs" tab to see execution

### Using the Console

1. **Connect to Server**
   ```
   Choose: 1 (Connect to server)
   ```

2. **Upload a File**
   ```
   Choose: 3 (Upload file)
   Local file: /path/to/local/file.txt
   Remote path: /remote/destination/file.txt
   ```

3. **Schedule a Task**
   ```
   Choose: 7 (Schedule task)
   Task type: 1 (Upload)
   Source: /path/to/local/backup.zip
   Destination: /remote/backups/backup.zip
   Run in minutes: 5
   Recurring: no
   ```

## Common Use Cases

### Automated Daily Backups

1. Create your backup file locally
2. Schedule an upload task:
   - Type: Upload
   - Source: `/home/user/backup.zip`
   - Destination: `/server/backups/daily_backup.zip`
   - Recurring: Yes
   - Interval: 1440 minutes (24 hours)
3. Start scheduler
4. Backups run automatically every 24 hours!

### Large File Transfer

1. Connect to server
2. Use Upload with large file
3. Progress bar shows transfer status
4. No manual monitoring needed

### Scheduled File Cleanup

1. Schedule delete tasks for temporary files
2. Set recurring interval (e.g., every 60 minutes)
3. Automatic cleanup runs in background

## Troubleshooting Quick Fixes

### "Cannot connect to server"
- **Check:** Is your server address correct in config.ini?
- **Check:** Is port 22 (or your custom port) accessible?
- **Check:** Are username/password correct?
- **Try:** `ssh username@host` to test connection

### "GUI won't start"
- **On Linux:** Install tkinter: `sudo apt-get install python3-tk`
- **Alternative:** Use console interface: `python main.py --console`

### "Module not found"
- **Run:** `pip install -r requirements.txt`
- **Check:** Python version is 3.7+ with `python3 --version`

### "Authentication failed"
- **Check:** Username and password in config.ini
- **Try:** SSH manually to verify credentials
- **Consider:** Using key-based authentication

## Tips & Tricks

1. **Keep Logs**: Check the "Logs" tab (GUI) to see what's happening
2. **Test First**: Test manual operations before scheduling
3. **Start Small**: Schedule tasks with short intervals (1-5 minutes) to test
4. **Stay Connected**: GUI maintains connection, console reconnects as needed
5. **Recurring Tasks**: Perfect for backups, monitoring, and cleanup

## Next Steps

- Read [README.md](README.md) for complete documentation
- Check [CHANGE_LOG.md](CHANGE_LOG.md) for version info
- Configure advanced settings in config.ini
- Set up multiple scheduled tasks
- Use both GUI and console as needed

## Need Help?

- Check README.md for detailed documentation
- Review error messages in Logs tab
- Verify config.ini settings
- Test connection manually with SSH first

---

**Ready to go!** 🚀

Start with: `python main.py` and click "Connect" in the Connection tab.
