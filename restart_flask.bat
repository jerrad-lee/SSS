@echo off
echo Stopping Flask...
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul
echo Clearing cache...
rd /s /q __pycache__ 2>nul
echo Starting Flask...
cd /d %~dp0
start /B "" "\\10.173.135.202\c$\FlaskDashboard\venv\Scripts\python.exe" app.py
echo Flask started!
timeout /t 3
