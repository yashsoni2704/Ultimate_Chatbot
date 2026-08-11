@echo off
setlocal EnableExtensions

:: ============================================================
::  DocMind — Application Launcher
::  This is what the Desktop shortcut runs.
::
::  Starts all 3 services in order:
::   1. Qdrant  (vector database)     — port 6333
::   2. Chat    (user chat app)        — port 5000
::   3. Admin   (admin panel)          — port 5001
::
::  Then opens the browser at http://localhost:5000
:: ============================================================

set "INSTALL_DIR=C:\DocMind"
set "PYTHON=%INSTALL_DIR%\env\Scripts\python.exe"
set "QDRANT=%INSTALL_DIR%\qdrant.exe"

title DocMind

echo.
echo  ==========================================
echo   DocMind - Starting...
echo  ==========================================
echo.

:: ── Check Python venv exists ─────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo  ERROR: Python environment not found at %INSTALL_DIR%\env
    echo  Please re-run DocMind_Setup.exe to repair the installation.
    pause
    exit /b 1
)

:: ── Check Qdrant binary ──────────────────────────────────────────────────
if not exist "%QDRANT%" (
    echo  ERROR: qdrant.exe not found at %QDRANT%
    echo  Please re-run DocMind_Setup.exe to repair the installation.
    pause
    exit /b 1
)

:: ── Kill anything already on ports 5000, 5001, 6333 ─────────────────────
echo  Clearing ports 5000, 5001, 6333...
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

:: ── Start Ollama (if not already running) ────────────────────────────────
echo  Checking Ollama...
curl -s http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    echo  Starting Ollama service...
    start /min "" ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo  Ollama already running.
)

:: ── [1/3] Start Qdrant ───────────────────────────────────────────────────
echo  [1/3] Starting Qdrant vector database (port 6333)...
start "DocMind - Qdrant" cmd /k ^
    "cd /d "%INSTALL_DIR%" && ^
     set QDRANT__STORAGE__STORAGE_PATH=%INSTALL_DIR%\vector_store && ^
     set QDRANT__SERVICE__HTTP_PORT=6333 && ^
     set QDRANT__LOG_LEVEL=WARN && ^
     "%QDRANT%""

:: Wait for Qdrant to be ready
echo  Waiting for Qdrant...
:WAIT_QDRANT
netstat -ano 2>nul | findstr ":6333 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto WAIT_QDRANT
)
echo  Qdrant ready.

:: ── [2/3] Start Chat server ──────────────────────────────────────────────
echo  [2/3] Starting Chat server (port 5000)...
set "TORCHDYNAMO_DISABLE=1"
set "TORCH_COMPILE_DISABLE=1"
start "DocMind - Chat :5000" cmd /k ^
    "cd /d "%INSTALL_DIR%" && ^
     set TORCHDYNAMO_DISABLE=1 && ^
     set TORCH_COMPILE_DISABLE=1 && ^
     "%PYTHON%" "%INSTALL_DIR%\watcher.py" app"

timeout /t 2 /nobreak >nul

:: ── [3/3] Start Admin server ─────────────────────────────────────────────
echo  [3/3] Starting Admin server (port 5001)...
start "DocMind - Admin :5001" cmd /k ^
    "cd /d "%INSTALL_DIR%" && ^
     set TORCHDYNAMO_DISABLE=1 && ^
     set TORCH_COMPILE_DISABLE=1 && ^
     "%PYTHON%" "%INSTALL_DIR%\watcher.py" admin"

:: ── Wait for Chat server then open browser ───────────────────────────────
echo  Waiting for chat server to be ready...
:WAIT_CHAT
netstat -ano 2>nul | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto WAIT_CHAT
)

echo.
echo  ==========================================
echo   DocMind is running!
echo   Chat  : http://localhost:5000
echo   Admin : http://localhost:5001/admin
echo  ==========================================
echo.

:: Open browser
start "" "http://localhost:5000"

exit /b 0
