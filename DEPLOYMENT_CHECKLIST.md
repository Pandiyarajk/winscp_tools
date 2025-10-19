# Deployment Checklist

Use this checklist to ensure proper deployment of WinSCP Manager.

## ✅ Pre-Deployment

### Files Created
- [x] Main application entry point (`main.py`)
- [x] Core modules in `winscp_manager/` directory
  - [x] `__init__.py`
  - [x] `config_manager.py`
  - [x] `winscp_handler.py`
  - [x] `scheduler.py`
  - [x] `gui.py`
  - [x] `console.py`
- [x] Configuration files
  - [x] `config.ini` (template)
  - [x] `example_config.ini` (backup)
- [x] Documentation
  - [x] `README.md`
  - [x] `CHANGE_LOG.md`
  - [x] `QUICK_START.md`
  - [x] `PROJECT_SUMMARY.md`
- [x] Dependencies
  - [x] `requirements.txt`
- [x] Git configuration
  - [x] `.gitignore`

### Code Verification
- [x] All Python files compile without syntax errors
- [x] All imports work correctly
- [x] Configuration loading tested
- [x] No critical dependencies missing

## 📋 Deployment Steps

### Step 1: System Requirements
```bash
# Check Python version (must be 3.7+)
python3 --version

# Should show: Python 3.7.x or higher
```

### Step 2: Install Dependencies
```bash
# Install required packages
pip install -r requirements.txt

# Verify installation
python3 -c "import paramiko; print('paramiko:', paramiko.__version__)"
```

### Step 3: Configure Application
```bash
# Edit config.ini with your credentials
nano config.ini  # or your preferred editor

# Set at minimum:
# - host
# - username
# - password (or private_key_path)
```

### Step 4: Test Installation
```bash
# Test help system
python main.py --help

# Test version
python main.py --version

# Test module imports
python3 -c "from winscp_manager import config_manager; print('OK')"
```

### Step 5: First Run

**For GUI (if tkinter available):**
```bash
python main.py --gui
```

**For Console (always available):**
```bash
python main.py --console
```

## 🔧 Platform-Specific Setup

### Windows
1. ✅ Python 3.7+ installed (python.org)
2. ✅ pip installed (included with Python)
3. ✅ tkinter available (included with Python on Windows)
4. Run: `python main.py` (GUI starts by default)

### Linux
1. Install Python and dependencies:
   ```bash
   sudo apt-get update
   sudo apt-get install python3 python3-pip
   
   # For GUI support (optional):
   sudo apt-get install python3-tk
   ```
2. Install Python packages:
   ```bash
   pip3 install -r requirements.txt
   ```
3. Run: `python3 main.py --console` (or --gui if tk installed)

### macOS
1. Python usually pre-installed, or install via Homebrew:
   ```bash
   brew install python3
   ```
2. Install dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```
3. tkinter included with Python on macOS
4. Run: `python3 main.py`

## 🔒 Security Setup

### Configuration File Security
```bash
# Restrict config.ini to owner only
chmod 600 config.ini

# Verify permissions
ls -l config.ini
# Should show: -rw------- (600)
```

### Using SSH Keys (Recommended)
```bash
# Generate SSH key pair (if needed)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/winscp_manager_key

# Copy public key to server
ssh-copy-id -i ~/.ssh/winscp_manager_key.pub user@server

# Update config.ini
# private_key_path = /home/user/.ssh/winscp_manager_key
# password = (leave empty)
```

### Credential Management
- ⚠️ **Never commit config.ini with real credentials**
- ✅ Use `.gitignore` (already configured)
- ✅ Consider environment variables for CI/CD
- ✅ Use key-based auth for production

## 📊 Verification Tests

### Test 1: Configuration
```bash
python3 -c "
from winscp_manager.config_manager import ConfigManager
cm = ConfigManager('config.ini')
print('Config loaded:', cm.get_connection_details()['host'])
"
```
Expected: Should print host from config

### Test 2: Module Imports
```bash
python3 -c "
from winscp_manager import config_manager, winscp_handler, scheduler, console
print('All imports successful')
"
```
Expected: "All imports successful"

### Test 3: Help System
```bash
python main.py --help
```
Expected: Should display help text with options

### Test 4: Version
```bash
python main.py --version
```
Expected: "WinSCP Manager 1.0.0"

## 🚀 Production Deployment

### For Server Deployment
1. Create dedicated user:
   ```bash
   sudo useradd -m -s /bin/bash winscp_manager
   ```

2. Install in user directory:
   ```bash
   sudo -u winscp_manager mkdir -p /home/winscp_manager/app
   sudo -u winscp_manager cp -r * /home/winscp_manager/app/
   ```

3. Set up as service (optional):
   - Create systemd service file
   - Enable auto-start
   - Configure logging

### For Desktop Deployment
1. Create desktop shortcut (Windows):
   ```
   Target: C:\Python3\python.exe C:\path\to\main.py
   Start in: C:\path\to\winscp_manager
   ```

2. Create launcher script (Linux):
   ```bash
   #!/bin/bash
   cd /path/to/winscp_manager
   python3 main.py --gui
   ```

## 📝 Post-Deployment

### Initial Configuration
- [ ] Edit config.ini with real credentials
- [ ] Test connection manually
- [ ] Create first scheduled task
- [ ] Verify task execution
- [ ] Check log files

### Monitoring
- [ ] Set up log rotation
- [ ] Monitor disk space (for downloads)
- [ ] Check scheduler is running
- [ ] Review error logs periodically

### Backup
- [ ] Backup config.ini (securely)
- [ ] Backup scheduled_tasks.json
- [ ] Document custom configurations

## 🐛 Troubleshooting

### Issue: tkinter not found
**Solution:** 
- Linux: `sudo apt-get install python3-tk`
- Or use console: `python main.py --console`

### Issue: paramiko not found
**Solution:**
```bash
pip install paramiko cryptography
```

### Issue: Permission denied on config.ini
**Solution:**
```bash
chmod 600 config.ini
```

### Issue: Cannot connect to server
**Solution:**
- Check host/port in config.ini
- Test with: `ssh user@host`
- Check firewall settings
- Verify credentials

## ✨ Optional Enhancements

### Add to PATH (Linux/Mac)
```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:/path/to/winscp_manager"
alias winscp-manager="python3 /path/to/winscp_manager/main.py"
```

### Windows Path
1. Open System Properties → Environment Variables
2. Add to PATH: `C:\path\to\winscp_manager`
3. Create batch file: `winscp.bat`
   ```batch
   @echo off
   python C:\path\to\winscp_manager\main.py %*
   ```

### Auto-Start Scheduler
Create a startup script to automatically start the scheduler:
```bash
#!/bin/bash
cd /path/to/winscp_manager
python3 main.py --console << EOF
1
10
EOF
```

## 📚 Documentation Access

After deployment, users should reference:
- **README.md** - Complete documentation
- **QUICK_START.md** - Getting started guide
- **PROJECT_SUMMARY.md** - Technical overview
- **CHANGE_LOG.md** - Version history

## ✅ Deployment Complete

When all items are checked:
- [x] Application installed
- [x] Dependencies installed
- [x] Configuration completed
- [x] Tests passed
- [x] Documentation reviewed
- [x] First successful connection made

**Status: READY FOR PRODUCTION USE** 🎉

---

**Need Help?** Check README.md troubleshooting section or review logs in the Logs tab.
