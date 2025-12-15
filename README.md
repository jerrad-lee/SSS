# Flask Dashboard - SKH Tool Information

## 📋 Project Overview

SKH Tool Information Dashboard - A web-based dashboard for managing and visualizing tool information with automatic startup capabilities and offline deployment support.

## 🎯 Features

- **Interactive Dashboard**: Color-coded table view of tool information
- **CSV Data Management**: Import and export tool data
- **Auto-Start Service**: Windows Task Scheduler or Service integration
- **Offline Deployment**: Complete offline installation package
- **Remote Access**: Network-accessible from multiple clients

## 📁 Project Structure

```
flask_dashboard_project/
├── app.py                          # Main Flask application
├── app_production.py               # Production version with logging
├── requirements.txt                # Python dependencies
├── data/
│   └── SKH_tool_information_fixed.csv  # Tool data (26 columns, 45 rows)
├── static/
│   └── style.css                   # Dashboard styling
├── templates/
│   └── dashboard.html              # Main dashboard template
├── deploy_bundle/                  # Offline deployment package
│   ├── app/                        # Application files
│   ├── wheels/                     # Python packages (offline)
│   ├── requirements.txt
│   ├── setup_task_scheduler.ps1    # Auto-start setup (Task Scheduler)
│   ├── setup_windows_service.ps1   # Auto-start setup (NSSM Service)
│   ├── flask_service.ps1           # Manual control script
│   ├── START_DASHBOARD.bat         # Quick start
│   ├── STOP_DASHBOARD.bat          # Quick stop
│   ├── STATUS_DASHBOARD.bat        # Status check
│   ├── AUTO_START_GUIDE.md         # Auto-start configuration guide
│   └── README.md                   # Deployment instructions
├── prepare_offline_bundle.ps1      # Creates offline deployment package
├── build_portable_exe.ps1          # Creates standalone executable
├── DEPLOYMENT_GUIDE.md             # Complete deployment documentation
├── QUICKSTART.md                   # Quick start guide
└── FlaskDashboard_Offline_Bundle_20251107.zip  # Ready-to-deploy package

```

## 🚀 Quick Start (Development)

### Local Development

```powershell
# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py

# Access dashboard
http://127.0.0.1:8060
```

## 📦 Deployment (Production Server)

### Option 1: Offline Installation (Recommended)

**Already prepared**: `FlaskDashboard_Offline_Bundle_20251107.zip`

1. **Transfer to server** (via USB/network)
2. **Extract** to `D:\Project\`
3. **Install Python 3.9+** on server
4. **Run installation**:
   ```powershell
   cd D:\Project\FlaskDashboard_Offline_Bundle_20251107
   
   # Set variables
   $INSTALL_DIR = "C:\FlaskDashboard"
   $PYTHON_EXE = "C:\Users\Lam\AppData\Local\Programs\Python\Python313\python.exe"
   
   # Create virtual environment
   & $PYTHON_EXE -m venv "$INSTALL_DIR\venv"
   
   # Install packages from wheels
   & "$INSTALL_DIR\venv\Scripts\pip.exe" install --no-index --find-links=".\wheels" -r requirements.txt
   
   # Copy application files
   Copy-Item -Path ".\app" -Destination $INSTALL_DIR -Recurse -Force
   ```

5. **Setup auto-start**:
   ```powershell
   cd C:\FlaskDashboard
   .\setup_task_scheduler.ps1
   ```

6. **Configure firewall**:
   ```powershell
   New-NetFirewallRule -DisplayName "Flask Dashboard" -Direction Inbound -Protocol TCP -LocalPort 8060 -Action Allow
   ```

### Option 2: Prepare New Offline Bundle

```powershell
# On internet-connected PC
.\prepare_offline_bundle.ps1

# Transfer generated ZIP to server
```

### Option 3: Standalone Executable (No Python Required)

```powershell
# On development PC
.\build_portable_exe.ps1

# Deploy to server (no Python installation needed)
```

## 🔧 Server Management

### Manual Control

```powershell
cd C:\FlaskDashboard

# Start
.\flask_service.ps1 start

# Stop
.\flask_service.ps1 stop

# Restart
.\flask_service.ps1 restart

# Status
.\flask_service.ps1 status
```

### Batch File Control (Double-click)

- **START_DASHBOARD.bat** - Start service
- **STOP_DASHBOARD.bat** - Stop service
- **STATUS_DASHBOARD.bat** - Check status

### Task Scheduler Commands

```powershell
# Start
Start-ScheduledTask -TaskName FlaskDashboard

# Stop
Stop-ScheduledTask -TaskName FlaskDashboard

# Status
Get-ScheduledTask -TaskName FlaskDashboard
```

## 🌐 Network Access

### Server Configuration

- **Server IP**: `10.173.135.202`
- **Port**: `8060`
- **Access URL**: `http://10.173.135.202:8060`

### Client Setup (Optional - Friendly Name)

Add to `C:\Windows\System32\drivers\etc\hosts` (admin PowerShell):

```powershell
Add-Content -Path C:\Windows\System32\drivers\etc\hosts -Value "10.173.135.202    dashboard.skh"
```

Then access via: `http://dashboard.skh:8060`

## 📊 Data Management

### CSV File Structure

- **File**: `data/SKH_tool_information_fixed.csv`
- **Columns**: 26 (Import, Fab, ToolID, FID, Platform, etc.)
- **Rows**: 45 tool records
- **Format**: UTF-8 CSV

### Download CSV

Visit: `http://10.173.135.202:8060/download_csv`

### Update Data

1. Edit `data/SKH_tool_information_fixed.csv`
2. Restart Flask service
3. Refresh browser

## 🛠️ Technical Details

### Dependencies

- **Flask** 3.0.0+ - Web framework
- **Pandas** 2.0.0+ - Data processing
- **Matplotlib** 3.7.0+ - Color generation
- **Waitress** 2.1.2+ - Production WSGI server (optional)

### System Requirements

- **OS**: Windows 10/11 or Windows Server
- **Python**: 3.9 or higher
- **RAM**: 512 MB minimum
- **Disk**: 200 MB (app + dependencies)

### Port Configuration

- **Default**: 8060
- **Binding**: 0.0.0.0 (all network interfaces)

## 📖 Documentation

- **DEPLOYMENT_GUIDE.md** - Complete deployment documentation (40+ sections)
- **QUICKSTART.md** - 5-minute quick start guide
- **AUTO_START_GUIDE.md** - Auto-start configuration (in deploy_bundle/)
- **deploy_bundle/README.md** - Offline deployment instructions

## 🔍 Troubleshooting

### Dashboard not accessible

```powershell
# Check process
Get-Process python | Where-Object {$_.CommandLine -like "*app.py*"}

# Check port
netstat -ano | findstr :8060

# Check firewall
Get-NetFirewallRule -DisplayName "Flask Dashboard"
```

### Service won't start

```powershell
# Check logs
Get-Content C:\FlaskDashboard\logs\service_output.log
Get-Content C:\FlaskDashboard\logs\service_error.log

# Manual test
cd C:\FlaskDashboard\app
C:\FlaskDashboard\venv\Scripts\python.exe app.py
```

### Network access issues

```powershell
# Test from client
ping 10.173.135.202

# Test port (PowerShell 3.0+)
Test-NetConnection -ComputerName 10.173.135.202 -Port 8060
```

## 📝 Version History

- **v1.0** (2025-11-07)
  - Initial release
  - 45 tool records (R3, M15, R4, NRD-P, NRD-K, P2F, P3H, P4H, NRD-V, NRD)
  - Auto-start capability (Task Scheduler / NSSM)
  - Offline deployment support
  - Network access configuration

## 👤 Author

Created for SKH tool information management

## 📄 License

Internal use only
