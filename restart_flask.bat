@echo off
echo ============================================
echo   Flask Dashboard Server Restart Script
echo ============================================
echo.

cd /d C:\FlaskDashboard\app

echo [1/3] Stopping existing Python processes...
taskkill /F /IM python.exe 2>nul
timeout /t 3 /nobreak >nul

echo [2/3] Clearing Python cache...
if exist __pycache__ rd /s /q __pycache__

echo [3/3] Starting Flask server...
start "Flask Dashboard" cmd /k "C:\FlaskDashboard\venv\Scripts\python.exe Main_SSS.py"

echo.
echo ============================================
echo   Flask server started!
echo   Access: http://10.173.135.202:8060/
echo ============================================
pause
