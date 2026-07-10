# NSSM Setup - Running Agent Brain as Windows Service

This guide explains how to run `agent.py` as a Windows background service using NSSM (Non-Sucking Service Manager), so the Market Lens agent brain runs continuously even when you're not logged in.

## What is NSSM?

NSSM is a free Windows service manager that wraps any executable (including Python scripts) as a proper Windows Service. It's the Windows equivalent of systemd on Linux.

**Download**: https://nssm.cc/download

## Prerequisites

1. **Python virtual environment** set up and activated
2. **PostgreSQL** installed and `market_lens` database created
3. **All dependencies** installed via `pip install -r requirements.txt`
4. **`.env` file** configured with all API keys
5. **`agent.py`** exists (will be created in Phase 14)

## Installation Steps

### 1. Download and Install NSSM

1. Download NSSM from https://nssm.cc/download
2. Extract the ZIP file
3. Copy `nssm.exe` from the `win64` folder to a permanent location, e.g.:
   ```
   C:\Program Files\NSSM\nssm.exe
   ```
4. (Optional) Add NSSM to your PATH for easier access

### 2. Prepare Python Environment

Create and activate a dedicated virtual environment:

```powershell
cd "C:\Users\User\.cursor\worktrees\Market_Lens\avi"
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

**Important**: Note the full path to your Python executable:
```
C:\Users\User\.cursor\worktrees\Market_Lens\avi\venv\Scripts\python.exe
```

### 3. Register the Service

Open PowerShell **as Administrator** and run:

```powershell
nssm install MarketLensAgent "C:\Users\User\.cursor\worktrees\Market_Lens\avi\venv\Scripts\python.exe" "C:\Users\User\.cursor\worktrees\Market_Lens\avi\agent.py"
```

This opens the NSSM service installer GUI. Configure:

**Application tab:**
- Path: `C:\Users\User\.cursor\worktrees\Market_Lens\avi\venv\Scripts\python.exe`
- Startup directory: `C:\Users\User\.cursor\worktrees\Market_Lens\avi`
- Arguments: `agent.py` (project root; Phase 14 creates avi/agent.py)

**Details tab:**
- Display name: `Market Lens Agent Brain`
- Description: `Market Lens active agent brain - monitors news, filings, and signals`
- Startup type: `Automatic`

**I/O tab:**
- Output (stdout): `C:\Users\User\.cursor\worktrees\Market_Lens\avi\logs\agent_stdout.log`
- Error (stderr): `C:\Users\User\.cursor\worktrees\Market_Lens\avi\logs\agent_stderr.log`

**File rotation tab:**
- Check "Rotate files"
- Rotate online: Yes
- Restrict rotation: 10 MB
- Rotate seconds: 86400 (daily)

Click **Install service**.

### 4. Start the Service

```powershell
nssm start MarketLensAgent
```

### 5. Verify It's Running

Check service status:
```powershell
nssm status MarketLensAgent
```

Check logs:
```powershell
Get-Content "C:\Users\User\.cursor\worktrees\Market_Lens\avi\logs\agent_stdout.log" -Tail 50
```

View in Windows Services:
```powershell
services.msc
```
Look for "Market Lens Agent Brain" - it should show status "Running".

## Management Commands

### Stop the service
```powershell
nssm stop MarketLensAgent
```

### Restart the service
```powershell
nssm restart MarketLensAgent
```

### Edit service configuration
```powershell
nssm edit MarketLensAgent
```

### Remove the service
```powershell
nssm remove MarketLensAgent confirm
```

## Testing Before Phase 14

Since `agent.py` doesn't exist yet, you can test NSSM with a dummy script:

**Create `test_service.py`:**
```python
import time
from datetime import datetime

while True:
    print(f"[{datetime.now()}] Market Lens agent brain test - running")
    time.sleep(60)
```

Register it with NSSM using the same steps above, but point to `test_service.py` instead of `agent.py`.

Start the service and check logs to confirm it's writing every 60 seconds.

Once confirmed working, stop and remove the test service:
```powershell
nssm stop MarketLensAgent
nssm remove MarketLensAgent confirm
```

## Troubleshooting

### Service won't start
- Check Python path is correct
- Verify virtual environment has all dependencies
- Check `.env` file exists and is readable
- Review stderr log for Python errors

### Service starts but crashes
- Check `agent_stderr.log` for Python exceptions
- Verify PostgreSQL is running and accessible
- Test `agent.py` manually first: `python agent.py` (from project root)

### Service doesn't restart after reboot
- Verify startup type is "Automatic"
- Check Windows Event Viewer for service errors
- Ensure PostgreSQL service starts before Market Lens

## Migration to Linux (Future)

When migrating to a Linux cloud instance, you'll replace NSSM with systemd:

**Create `/etc/systemd/system/market-lens-agent.service`:**
```ini
[Unit]
Description=Market Lens Agent Brain
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/opt/market_lens
ExecStart=/opt/market_lens/venv/bin/python /opt/market_lens/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl enable market-lens-agent
sudo systemctl start market-lens-agent
sudo systemctl status market-lens-agent
```

The Python code in `agent.py` remains **identical** - only the process manager changes.

## Next Steps

1. Complete Phase 2-13 to build the full agent brain
2. Test `agent.py` manually before registering as service
3. Register with NSSM once agent brain is working
4. Configure Windows to never sleep (Power Settings)
5. Monitor logs for first 24 hours to ensure stability
