@echo off
echo Installing required packages...
cd /d C:\FlaskDashboard
call venv\Scripts\activate.bat
pip install PyMuPDF requests
echo.
echo Installation complete!
echo.
echo Now restarting Flask...
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul
start "Flask Dashboard" cmd /c "C:\FlaskDashboard\venv\Scripts\python.exe app.py"
echo Flask started!
pause