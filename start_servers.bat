@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%Yash\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"

title DocMind - Start Servers

echo.
echo  ==========================================
echo   DocMind - Starting All Servers
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

echo  [1/2] Starting User Chat App (port 5000)...
start "DocMind Chat - Port 5000" cmd /k "cd /d ""%ROOT%"" && set PYTHONIOENCODING=utf-8 && echo. && echo  ====================================== && echo   User Chat App && echo   URL : http://localhost:5000 && echo  ====================================== && echo. && ""%PYTHON_EXE%"" app.py"

timeout /t 2 /nobreak >nul

echo  [2/2] Starting Admin Panel (port 5001)...
start "DocMind Admin - Port 5001" cmd /k "cd /d ""%ROOT%"" && set PYTHONIOENCODING=utf-8 && echo. && echo  ====================================== && echo   Admin Panel && echo   URL : http://localhost:5001/admin && echo  ====================================== && echo. && ""%PYTHON_EXE%"" admin_app.py"

echo.
echo  ==========================================
echo   Both servers are starting up!
echo  ------------------------------------------
echo   User Chat  :  http://localhost:5000
echo   Admin Panel:  http://localhost:5001/admin
echo  ==========================================
echo.
exit /b 0
