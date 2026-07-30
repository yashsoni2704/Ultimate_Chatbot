@echo off
setlocal EnableExtensions
title DocMind - Stop Servers

echo.
echo  Stopping all DocMind servers...

:: Kill terminal windows by title
taskkill /FI "WINDOWTITLE eq DocMind Qdrant :6333" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DocMind Chat :5000"   /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DocMind Admin :5001"  /T /F >nul 2>&1

:: Kill python processes (app, admin, watcher)
for /f "tokens=*" %%P in ('powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -match 'app\.py|admin_app\.py|watcher\.py') } | Select-Object -ExpandProperty ProcessId" 2^>nul') do (
    taskkill /PID %%P /F >nul 2>&1
)

:: Kill qdrant.exe
taskkill /IM qdrant.exe /F >nul 2>&1

:: Kill anything still on ports 5000, 5001, 6333
for %%P in (5000 5001 6333) do (
    for /f "tokens=5" %%A in ('netstat -aon 2^>nul ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        taskkill /PID %%A /F >nul 2>&1
    )
)

echo  All servers stopped.
echo.
exit /b 0
