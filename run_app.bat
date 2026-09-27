@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 launcher was not found. Install Python 3 and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

set PORT=8501
netstat -ano | findstr ":8501" | findstr "LISTENING" >nul
if not errorlevel 1 set PORT=8502

".venv\Scripts\python.exe" -m streamlit run app.py --server.port %PORT%
if errorlevel 1 goto failed
goto end

:failed
echo.
echo Setup or startup failed. Check the message above and try again.
pause

:end
endlocal
