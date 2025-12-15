# Flask Dashboard Task Scheduler Setup Script
# Windows 시작 시 자동 실행 설정

Write-Host "=== Flask Dashboard Task Scheduler Setup ===" -ForegroundColor Cyan

$taskName = "FlaskDashboard"
$pythonExe = "C:\FlaskDashboard\venv\Scripts\python.exe"
$appPath = "C:\FlaskDashboard\app\app.py"
$workingDir = "C:\FlaskDashboard\app"
$logFile = "C:\FlaskDashboard\logs\task_output.log"

# Create log directory
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Write-Host "`n[1] Check and remove existing task" -ForegroundColor Yellow
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Write-Host "`n[2] Create scheduled task" -ForegroundColor Yellow

# Task action definition
$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument $appPath `
    -WorkingDirectory $workingDir

# Trigger: At system startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Settings: Always run, ignore power management
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Principal: Run as SYSTEM account
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Register task
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Flask Dashboard Auto-Start Service" `
    -Force

Write-Host "`n[3] Start task" -ForegroundColor Yellow
Start-ScheduledTask -TaskName $taskName

Start-Sleep -Seconds 3

# Check task status
$task = Get-ScheduledTask -TaskName $taskName
Write-Host "`nTask status: $($task.State)" -ForegroundColor Green

# Check process
$pythonProcess = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*app.py*" }
if ($pythonProcess) {
    Write-Host "Flask app running (PID: $($pythonProcess.Id))" -ForegroundColor Green
} else {
    Write-Host "Flask app not detected - check logs" -ForegroundColor Yellow
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "`nTask management commands:" -ForegroundColor Cyan
Write-Host "  Start:  Start-ScheduledTask -TaskName FlaskDashboard" -ForegroundColor White
Write-Host "  Stop:   Stop-ScheduledTask -TaskName FlaskDashboard (then kill process manually)" -ForegroundColor White
Write-Host "  Status: Get-ScheduledTask -TaskName FlaskDashboard" -ForegroundColor White
Write-Host "  Remove: Unregister-ScheduledTask -TaskName FlaskDashboard -Confirm:`$false" -ForegroundColor White
Write-Host "`nGUI: taskschd.msc (Task Scheduler)" -ForegroundColor Cyan
Write-Host "`nNote: Task Scheduler does not auto-kill process on stop." -ForegroundColor Yellow
Write-Host "Manual kill: Get-Process python | Where-Object {`$_.CommandLine -like '*app.py*'} | Stop-Process -Force" -ForegroundColor Yellow
