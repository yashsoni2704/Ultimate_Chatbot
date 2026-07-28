@echo off
title DocMind — Start Servers

echo.
echo  ==========================================
echo   DocMind — Starting All Servers
echo  ==========================================
echo.

:: Start user chat app on port 5000
echo  [1/2] Starting User Chat App (port 5000)...
start "DocMind Chat - Port 5000" cmd /k "cd /d %~dp0 && chatbot_test_env\Scripts\python.exe app.py"

:: Small delay so ports don't collide on startup
timeout /t 2 /nobreak >nul

:: Start admin panel on port 5001
echo  [2/2] Starting Admin Panel (port 5001)...
start "DocMind Admin - Port 5001" cmd /k "cd /d %~dp0 && chatbot_test_env\Scripts\python.exe admin_app.py"

echo.
echo  ==========================================
echo   Both servers are starting up!
echo  ------------------------------------------
echo   User Chat  :  http://localhost:5000
echo   Admin Panel:  http://localhost:5001/admin
echo  ==========================================
echo.
pause
