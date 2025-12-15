# Flask Dashboard Service Control Script
# 서비스 시작/중지/재시작/상태 확인

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action
)

$serviceName = "FlaskDashboard"
$pythonExe = "C:\FlaskDashboard\venv\Scripts\python.exe"
$appPath = "C:\FlaskDashboard\app.py"
$workingDir = "C:\FlaskDashboard"

function Start-FlaskApp {
    Write-Host "Starting Flask Dashboard..." -ForegroundColor Cyan

    # Check existing process
    $existing = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $pythonExe }
    if ($existing) {
        Write-Host "Already running (PID: $($existing.Id))" -ForegroundColor Yellow
        return
    }

    # Run in background
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList $appPath `
        -WorkingDirectory $workingDir `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2

    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Write-Host "Started successfully (PID: $($process.Id))" -ForegroundColor Green
        Write-Host "Access: http://10.173.135.202:8060" -ForegroundColor Cyan
    } else {
        Write-Host "Failed to start - check logs" -ForegroundColor Red
    }
}

function Stop-FlaskApp {
    Write-Host "Stopping Flask Dashboard..." -ForegroundColor Cyan

    $processes = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $pythonExe }

    if (-not $processes) {
        Write-Host "No running process found" -ForegroundColor Yellow
        return
    }

    foreach ($proc in $processes) {
        Stop-Process -Id $proc.Id -Force
        Write-Host "Process stopped (PID: $($proc.Id))" -ForegroundColor Green
    }
}

function Restart-FlaskApp {
    Write-Host "Restarting Flask Dashboard..." -ForegroundColor Cyan
    Stop-FlaskApp
    Start-Sleep -Seconds 2
    Start-FlaskApp
}

function Get-FlaskAppStatus {
    Write-Host "`n=== Flask Dashboard Status ===" -ForegroundColor Cyan

    # Check process
    $processes = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $pythonExe }

    if ($processes) {
        Write-Host "`nStatus: Running" -ForegroundColor Green
        foreach ($proc in $processes) {
            Write-Host "  PID: $($proc.Id)" -ForegroundColor White
            Write-Host "  Memory: $([math]::Round($proc.WorkingSet64/1MB, 2)) MB" -ForegroundColor White
            Write-Host "  Start Time: $($proc.StartTime)" -ForegroundColor White
        }
    } else {
        Write-Host "`nStatus: Stopped" -ForegroundColor Red
    }

    # Check port
    Write-Host "`nPort 8060 status:" -ForegroundColor Cyan
    $port = netstat -ano | findstr ":8060.*LISTENING"
    if ($port) {
        Write-Host "  $port" -ForegroundColor Green
    } else {
        Write-Host "  Port not in use" -ForegroundColor Yellow
    }

    # Check Task Scheduler
    $task = Get-ScheduledTask -TaskName "FlaskDashboard" -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "`nTask Scheduler: $($task.State)" -ForegroundColor Cyan
    }

    # Check Windows Service (NSSM)
    $service = Get-Service -Name "FlaskDashboard" -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Windows Service: $($service.Status)" -ForegroundColor Cyan
    }

    Write-Host ""
}

# 메인 실행
switch ($Action) {
    "start"   { Start-FlaskApp }
    "stop"    { Stop-FlaskApp }
    "restart" { Restart-FlaskApp }
    "status"  { Get-FlaskAppStatus }
}
