"""Write start_servers.bat and stop_servers.bat as plain ASCII with CRLF line endings."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

START = (
    "@echo off\r\n"
    "setlocal EnableExtensions\r\n"
    "\r\n"
    'set "ROOT=%~dp0"\r\n'
    'set "PYTHON=%ROOT%Yash\\Scripts\\python.exe"\r\n'
    'set "QDRANT=%ROOT%qdrant.exe"\r\n'
    'set "LOGS=%ROOT%logs"\r\n'
    'set "PYTHONIOENCODING=utf-8"\r\n'
    'set "PYTHONUNBUFFERED=1"\r\n'
    "\r\n"
    "title DocMind - Start Servers\r\n"
    "\r\n"
    "echo.\r\n"
    "echo  ==========================================\r\n"
    "echo   DocMind - Starting All Servers\r\n"
    "echo  ==========================================\r\n"
    "echo.\r\n"
    "\r\n"
    'if not exist "%PYTHON%" (\r\n'
    '    echo  ERROR: Python not found at: %PYTHON%\r\n'
    "    pause\r\n"
    "    exit /b 1\r\n"
    ")\r\n"
    "\r\n"
    'if not exist "%QDRANT%" (\r\n'
    '    echo  ERROR: qdrant.exe not found at: %QDRANT%\r\n'
    "    pause\r\n"
    "    exit /b 1\r\n"
    ")\r\n"
    "\r\n"
    'if not exist "%LOGS%" mkdir "%LOGS%"\r\n'
    "\r\n"
    "echo  Killing any process on ports 5000, 5001 and 6333...\r\n"
    'for /f "tokens=5" %%P in (\'netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"\') do (\r\n'
    "    taskkill /PID %%P /F >nul 2>&1\r\n"
    ")\r\n"
    'for /f "tokens=5" %%P in (\'netstat -ano 2^>nul ^| findstr ":5001 " ^| findstr "LISTENING"\') do (\r\n'
    "    taskkill /PID %%P /F >nul 2>&1\r\n"
    ")\r\n"
    'for /f "tokens=5" %%P in (\'netstat -ano 2^>nul ^| findstr ":6333 " ^| findstr "LISTENING"\') do (\r\n'
    "    taskkill /PID %%P /F >nul 2>&1\r\n"
    ")\r\n"
    "timeout /t 1 /nobreak >nul\r\n"
    "\r\n"
    "echo  [1/3] Starting Qdrant (port 6333) ...\r\n"
    'start "DocMind Qdrant :6333" cmd /k "cd /d "%ROOT%" && set QDRANT__STORAGE__STORAGE_PATH=%ROOT%vector_store && set QDRANT__SERVICE__HTTP_PORT=6333 && set QDRANT__LOG_LEVEL=WARN && "%QDRANT%""\r\n'
    "\r\n"
    "echo  Waiting for Qdrant on port 6333...\r\n"
    ":WAIT_QDRANT\r\n"
    'netstat -ano 2>nul | findstr ":6333 " | findstr "LISTENING" >nul 2>&1\r\n'
    "if errorlevel 1 (\r\n"
    "    timeout /t 2 /nobreak >nul\r\n"
    "    goto WAIT_QDRANT\r\n"
    ")\r\n"
    "echo  Qdrant ready.\r\n"
    "\r\n"
    "echo  [2/3] Starting Chat server (port 5000) ...\r\n"
    'start "DocMind Chat :5000" cmd /k "cd /d "%ROOT%" && set PYTHONIOENCODING=utf-8 && set PYTHONUNBUFFERED=1 && "%PYTHON%" "%ROOT%watcher.py" app"\r\n'
    "\r\n"
    "timeout /t 2 /nobreak >nul\r\n"
    "\r\n"
    "echo  [3/3] Starting Admin server (port 5001) ...\r\n"
    'start "DocMind Admin :5001" cmd /k "cd /d "%ROOT%" && set PYTHONIOENCODING=utf-8 && set PYTHONUNBUFFERED=1 && "%PYTHON%" "%ROOT%watcher.py" admin"\r\n'
    "\r\n"
    "echo.\r\n"
    "echo  ==========================================\r\n"
    "echo   Qdrant : http://localhost:6333\r\n"
    "echo   Chat   : http://localhost:5000\r\n"
    "echo   Admin  : http://localhost:5001/admin\r\n"
    "echo   Logs   : logs\\app_*.log\r\n"
    "echo  ==========================================\r\n"
    "echo.\r\n"
    "exit /b 0\r\n"
)

STOP = (
    "@echo off\r\n"
    "setlocal EnableExtensions\r\n"
    "title DocMind - Stop Servers\r\n"
    "\r\n"
    "echo.\r\n"
    "echo  Stopping all DocMind servers...\r\n"
    "\r\n"
    'taskkill /FI "WINDOWTITLE eq DocMind Qdrant :6333" /T /F >nul 2>&1\r\n'
    'taskkill /FI "WINDOWTITLE eq DocMind Chat :5000"   /T /F >nul 2>&1\r\n'
    'taskkill /FI "WINDOWTITLE eq DocMind Admin :5001"  /T /F >nul 2>&1\r\n'
    "\r\n"
    "taskkill /IM qdrant.exe /F >nul 2>&1\r\n"
    "\r\n"
    "for %%P in (5000 5001 6333) do (\r\n"
    '    for /f "tokens=5" %%A in (\'netstat -aon 2^>nul ^| findstr ":%%P " ^| findstr "LISTENING"\') do (\r\n'
    "        taskkill /PID %%A /F >nul 2>&1\r\n"
    "    )\r\n"
    ")\r\n"
    "\r\n"
    "timeout /t 1 /nobreak >nul\r\n"
    "echo  All servers stopped.\r\n"
    "echo.\r\n"
    "pause\r\n"
    "exit /b 0\r\n"
)

start_path = os.path.join(ROOT, "start_servers.bat")
stop_path  = os.path.join(ROOT, "stop_servers.bat")

with open(start_path, "wb") as f:
    f.write(START.encode("ascii"))

with open(stop_path, "wb") as f:
    f.write(STOP.encode("ascii"))

print(f"Written: {start_path}")
print(f"Written: {stop_path}")
