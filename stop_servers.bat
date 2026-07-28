@echo off
title DocMind — Stop Servers

echo.
echo  ==========================================
echo   DocMind — Stopping All Servers
echo  ==========================================
echo.

:: Kill any python process running app.py or admin_app.py
echo  Stopping processes on port 5000 and 5001...

:: Find and kill processes on port 5000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    echo  Killing PID %%a (port 5000)
    taskkill /PID %%a /F >nul 2>&1
)

:: Find and kill processes on port 5001
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5001 " ^| findstr "LISTENING"') do (
    echo  Killing PID %%a (port 5001)
    taskkill /PID %%a /F >nul 2>&1
)

:: Also close the terminal windows by title
taskkill /FI "WINDOWTITLE eq DocMind Chat - Port 5000" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DocMind Admin - Port 5001" /F >nul 2>&1

echo.
echo  ==========================================
echo   All DocMind servers stopped.
echo  ==========================================
echo.
pause
