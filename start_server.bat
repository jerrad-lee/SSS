@echo off
REM Start Flask Dashboard on Server
cd /d C:\FlaskDashboard\app
start /B ..\venv\Scripts\python.exe Main_SSS.py
echo Flask started successfully!
echo Check: http://10.173.135.202:8060
timeout /t 3
