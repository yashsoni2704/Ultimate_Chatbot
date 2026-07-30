@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PYTHON=%ROOT%Yash\Scripts\python.exe"
set "QDRANT=%ROOT%qdrant.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

title DocMind - Start Servers

echo.
echo  ==========================================
echo   DocMind - Starting All Servers
echo  ==========================================
echo.

if not exist "%PYTHON%" (
    echo  ERROR: Python not found at: %PYTHON%
    pause
    exit /b 1
)

if not exist "%QDRANT%" (
    echo  ERROR: qdrant.exe not found at: %QDRANT%
    pause
    exit /b 1
)

echo  Killing any process on ports 5000, 5001 and 6333...
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":5001 " ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":6333 " ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo  [1/3] Starting Qdrant vector database (port 6333) ...
start "DocMind Qdrant :6333" cmd /k "cd /d "%ROOT%" && set QDRANT__STORAGE__STORAGE_PATH=%ROOT%vector_store && set QDRANT__SERVICE__HTTP_PORT=6333 && set QDRANT__LOG_LEVEL=WARN && "%QDRANT%""

echo  Waiting for Qdrant to be ready on port 6333...
:WAIT_QDRANT
netstat -ano 2>nul | findstr ":6333 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto WAIT_QDRANT
)
echo  Qdrant is ready.

echo  [2/3] Starting Chat server  (port 5000) ...
start "DocMind Chat :5000" cmd /k "%PYTHON% "%ROOT%watcher.py" app"

timeout /t 2 /nobreak >nul

echo  [3/3] Starting Admin server (port 5001) ...
start "DocMind Admin :5001" cmd /k "%PYTHON% "%ROOT%watcher.py" admin"

echo.
echo  ==========================================
echo   Qdrant  :  http://localhost:6333
echo   Chat    :  http://localhost:5000
echo   Admin   :  http://localhost:5001/admin
echo  ==========================================
echo.
exit /b 0
