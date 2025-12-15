@echo off
cd /d C:\FlaskDashboard
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul
C:\FlaskDashboard\venv\Scripts\python.exe app.py
