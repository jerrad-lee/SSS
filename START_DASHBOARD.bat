@echo off
chcp 65001 > nul
echo ========================================
echo   Flask Dashboard ?? ??
echo ========================================
echo.

cd /d C:\FlaskDashboard

echo [1/3] ?? ?? ?...
if exist __pycache__ rd /s /q __pycache__ 2>nul

echo [2/3] Python ?? ?? ?...
set PYTHON=venv\Scripts\python.exe

echo [3/3] Flask ?? ?? ?...
echo   ? Port: 8060
echo   ? URL: http://10.173.135.202:8060
echo.
echo ========================================
echo   ??? ???? ?????? ?????
echo   ??: Ctrl+C
echo ========================================
echo.

%PYTHON% app.py
pause
