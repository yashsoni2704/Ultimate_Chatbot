@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%Yash\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

title DocMind - Start Servers

echo.
echo  ==========================================
echo   DocMind - Starting All Servers
echo   (auto-restart on code change or crash)
echo  ==========================================
echo.

if not exist "%PYTHON_EXE%" (
    echo  ERROR: Python interpreter not found at "%PYTHON_EXE%"
    echo  Please make sure the Yash environment exists.
    pause
    exit /b 1
)

echo  Stopping any existing servers on ports 5000 and 5001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 1 /nobreak >nul

echo  [1/2] Starting Chat watcher (port 5000)...
start "DocMind Chat - Port 5000" cmd /k ^
  "cd /d ""%ROOT%"" ^
  && set PYTHONIOENCODING=utf-8 ^
  && set PYTHONUNBUFFERED=1 ^
  && echo. ^
  && echo  ====================================== ^
  && echo   User Chat App  [AUTO-RESTART ON] ^
  && echo   URL : http://localhost:5000 ^
  && echo  ====================================== ^
  && echo. ^
  && ""%PYTHON_EXE%"" watcher.py app"

timeout /t 2 /nobreak >nul

echo  [2/2] Starting Admin watcher (port 5001)...
start "DocMind Admin - Port 5001" cmd /k ^
  "cd /d ""%ROOT%"" ^
  && set PYTHONIOENCODING=utf-8 ^
  && set PYTHONUNBUFFERED=1 ^
  && echo. ^
  && echo  ====================================== ^
  && echo   Admin Panel    [AUTO-RESTART ON] ^
  && echo   URL : http://localhost:5001/admin ^
  && echo  ====================================== ^
  && echo. ^
  && ""%PYTHON_EXE%"" watcher.py admin"

echo.
echo  ==========================================
echo   Both servers are running with auto-restart!
echo  ------------------------------------------
echo   User Chat  :  http://localhost:5000
echo   Admin Panel:  http://localhost:5001/admin
echo  ------------------------------------------
echo   Changes to .py / .html / .css / .js
echo   files will trigger an instant restart.
echo   Crashes are recovered in 2 seconds.
echo  ==========================================
echo.
exit /b 0
