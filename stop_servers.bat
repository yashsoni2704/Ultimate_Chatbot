@echo off
setlocal EnableExtensions
title DocMind - Stop Servers

echo.
echo  ==========================================
echo   DocMind - Stopping All Servers
echo  ==========================================
echo.

:: ── Round 1: Kill by window title (cmd /k windows started by start_servers.bat) ──
echo  [1/5] Killing windows by title...
taskkill /FI "WINDOWTITLE eq DocMind Qdrant :6333" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DocMind Chat :5000"   /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DocMind Admin :5001"  /T /F >nul 2>&1

:: ── Round 2: Kill qdrant.exe by image name (catches all instances) ──
echo  [2/5] Killing qdrant.exe...
taskkill /IM qdrant.exe /T /F >nul 2>&1

:: ── Round 3: Kill Python processes running our scripts ──
echo  [3/5] Killing Python app/admin/watcher processes...
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process ^
     | Where-Object { $_.Name -eq 'python.exe' -and ^
         ($_.CommandLine -match 'app\.py|admin_app\.py|watcher\.py') } ^
     | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" ^
    >nul 2>&1

:: ── Round 4: Force-kill anything still holding our ports ──
echo  [4/5] Releasing ports 5000, 5001, 6333...
for %%P in (5000 5001 6333) do (
    for /f "tokens=5" %%A in ('netstat -aon 2^>nul ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        taskkill /PID %%A /T /F >nul 2>&1
    )
)

:: ── Round 5: Wait and verify ──
echo  [5/5] Verifying ports are free...
timeout /t 2 /nobreak >nul

set "STILL_BUSY="
for %%P in (5000 5001 6333) do (
    netstat -aon 2>nul | findstr ":%%P " | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 (
        set "STILL_BUSY=%%P"
        echo   WARNING: Port %%P is still in use. You may need to reboot or wait.
    )
)

if not defined STILL_BUSY (
    echo.
    echo  ==========================================
    echo   All servers stopped. Ports 5000, 5001,
    echo   and 6333 are now free.
    echo  ==========================================
) else (
    echo.
    echo  ==========================================
    echo   Some ports may still be occupied.
    echo   Run this script again in a few seconds,
    echo   or restart your machine if it persists.
    echo  ==========================================
)

echo.
pause
exit /b 0
