@echo off
chcp 65001 >nul
echo ========================================
echo Flask Dashboard - 중지
echo ========================================
echo.

powershell -ExecutionPolicy Bypass -Command "cd C:\FlaskDashboard ; .\flask_service.ps1 stop"

echo.
pause
