@echo off
echo Restarting Flask...
cd /d C:\FlaskDashboard\app
taskkill /F /IM python.exe 2>nul
timeout /t 3 /nobreak >nul
rd /s /q __pycache__ 2>nul
start "Flask" cmd /k "C:\FlaskDashboard\venv\Scripts\python.exe Main_SSS.py"
echo Done!
