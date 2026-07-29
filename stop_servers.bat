@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
title DocMind — Stop Servers

echo.
echo  ==========================================
echo   DocMind — Stopping All Servers
echo  ==========================================
echo.

echo  Stopping DocMind chat and admin processes...

:: Stop the launched terminal windows by title
for %%T in ("DocMind Chat - Port 5000" "DocMind Admin - Port 5001") do (
    taskkill /FI "WINDOWTITLE eq %%~T" /T /F >nul 2>&1
)

:: Stop any python process running the app entry points
for /f %%P in ('powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -match 'app.py' -or $_.CommandLine -match 'admin_app.py') } | Select-Object -ExpandProperty ProcessId" 2^>nul') do (
    taskkill /PID %%P /F >nul 2>&1
)

:: Stop anything still listening on the app ports
for %%P in (5000 5001) do (
    for /f "tokens=5" %%A in ('netstat -aon ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        taskkill /PID %%A /F >nul 2>&1
    )
)

echo.
echo  ==========================================
echo   All DocMind servers stopped.
echo  ==========================================
echo.
exit /b 0
