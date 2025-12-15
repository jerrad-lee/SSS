# Server Update Script - Run this on server 10.173.135.202

Write-Host "Installing openpyxl package..." -ForegroundColor Yellow
C:\FlaskDashboard\venv\Scripts\pip.exe install openpyxl

Write-Host "`nRestarting Flask service..." -ForegroundColor Yellow
Set-Location C:\FlaskDashboard

# Stop existing Flask process
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Start Flask service
.\flask_service.ps1 start

Write-Host "`n✓ Server updated successfully!" -ForegroundColor Green
Write-Host "Dashboard running at: http://10.173.135.202:8060" -ForegroundColor Cyan
