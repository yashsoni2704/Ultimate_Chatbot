@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "QDRANT=%ROOT%qdrant.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

:: Disable torch JIT compiler (requires cl.exe / MSVC which is not installed).
:: Without this, Docling's model compilation fails and OCR breaks.
set "TORCHDYNAMO_DISABLE=1"
set "TORCH_COMPILE_DISABLE=1"

title DocMind - Start Servers

echo.
echo  ==========================================
echo   DocMind - Starting All Servers
echo  ==========================================
echo.

:: ── Auto-detect Python from the project venv ─────────────────────────────
:: Priority 1: Yash\Scripts\python.exe  (original dev machine)
:: Priority 2: any venv\Scripts\python.exe found one level down
:: Priority 3: python on system PATH
set "PYTHON="

if exist "%ROOT%Yash\Scripts\python.exe" (
    set "PYTHON=%ROOT%Yash\Scripts\python.exe"
    goto :python_found
)

:: Scan for any venv folder containing Scripts\python.exe
for /d %%V in ("%ROOT%*") do (
    if exist "%%V\Scripts\python.exe" (
        set "PYTHON=%%V\Scripts\python.exe"
        goto :python_found
    )
)

:: Last resort — system python
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :python_found
)

echo  ERROR: No Python interpreter found.
echo  Please create a virtual environment in the project folder, e.g.:
echo    python -m venv venv
echo    venv\Scripts\pip install -r requirements.txt
pause
exit /b 1

:python_found
echo  Python : %PYTHON%


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
start "DocMind Qdrant :6333" cmd /k "cd /d ""%ROOT%"" && set ""QDRANT__STORAGE__STORAGE_PATH=%ROOT%vector_store"" && set ""QDRANT__SERVICE__HTTP_PORT=6333"" && set ""QDRANT__LOG_LEVEL=WARN"" && ""%QDRANT%"""

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
