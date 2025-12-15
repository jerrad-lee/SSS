@echo off
echo Restarting Flask Dashboard...
taskkill /F /IM python.exe 2>nul
timeout /t 3 >nul
cd /d C:\FlaskDashboard\app
start /min pythonw Main_SSS.py
echo Flask restarted!
