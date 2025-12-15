@echo off
chcp 65001 >nul
echo ========================================
echo Flask Dashboard - 상태 확인
echo ========================================
echo.

powershell -ExecutionPolicy Bypass -Command "cd C:\FlaskDashboard ; .\flask_service.ps1 status"

echo.
pause
