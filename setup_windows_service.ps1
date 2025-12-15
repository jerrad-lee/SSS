# Flask Dashboard Windows Service Setup Script
# NSSM을 사용하여 Windows 서비스로 등록

Write-Host "=== Flask Dashboard Service Setup ===" -ForegroundColor Cyan

# NSSM download URL (manual download required for offline environment)
$nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
$nssmPath = "C:\FlaskDashboard\nssm.exe"

Write-Host "`n[1] Check NSSM installation" -ForegroundColor Yellow

if (-not (Test-Path $nssmPath)) {
    Write-Host "NSSM is not installed." -ForegroundColor Red
    Write-Host "To install NSSM:" -ForegroundColor Yellow
    Write-Host "1. Download from internet-connected PC: $nssmUrl" -ForegroundColor White
    Write-Host "2. Extract nssm-2.24.zip" -ForegroundColor White
    Write-Host "3. Copy win64\nssm.exe to C:\FlaskDashboard\nssm.exe" -ForegroundColor White
    Write-Host "`nOr use Task Scheduler method instead." -ForegroundColor Cyan
    exit 1
}

Write-Host "NSSM found: $nssmPath" -ForegroundColor Green

# Service settings
$serviceName = "FlaskDashboard"
$pythonExe = "C:\FlaskDashboard\venv\Scripts\python.exe"
$appPath = "C:\FlaskDashboard\app\app.py"
$appDir = "C:\FlaskDashboard\app"

Write-Host "`n[2] Register service" -ForegroundColor Yellow

# Check and remove existing service
$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Removing existing service..." -ForegroundColor Yellow
    & $nssmPath stop $serviceName
    & $nssmPath remove $serviceName confirm
    Start-Sleep -Seconds 2
}

# Install service
Write-Host "Installing service..." -ForegroundColor Cyan
& $nssmPath install $serviceName $pythonExe $appPath

# Configure service
& $nssmPath set $serviceName AppDirectory $appDir
& $nssmPath set $serviceName DisplayName "Flask Dashboard Service"
& $nssmPath set $serviceName Description "SKH Tool Information Dashboard"
& $nssmPath set $serviceName Start SERVICE_AUTO_START
& $nssmPath set $serviceName AppStdout "C:\FlaskDashboard\logs\service_output.log"
& $nssmPath set $serviceName AppStderr "C:\FlaskDashboard\logs\service_error.log"
& $nssmPath set $serviceName AppRotateFiles 1
& $nssmPath set $serviceName AppRotateBytes 1048576  # 1MB

Write-Host "`n[3] Start service" -ForegroundColor Yellow
& $nssmPath start $serviceName

Start-Sleep -Seconds 3

# Check service status
$service = Get-Service -Name $serviceName
Write-Host "`nService status: $($service.Status)" -ForegroundColor Green

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "`nService management commands:" -ForegroundColor Cyan
Write-Host "  Start:   net start FlaskDashboard" -ForegroundColor White
Write-Host "  Stop:    net stop FlaskDashboard" -ForegroundColor White
Write-Host "  Restart: net stop FlaskDashboard && net start FlaskDashboard" -ForegroundColor White
Write-Host "  Status:  Get-Service FlaskDashboard" -ForegroundColor White
Write-Host "  Remove:  C:\FlaskDashboard\nssm.exe remove FlaskDashboard confirm" -ForegroundColor White
Write-Host "`nGUI: services.msc (Windows Service Manager)" -ForegroundColor Cyan
