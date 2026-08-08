@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"

title DocMind - Reset Vector & Upload Data
echo.
echo  ==========================================
echo   DocMind - Reset Vector DB and Uploads
echo  ==========================================
echo.
echo  This permanently removes:
echo    - Uploaded document files  (uploads\)
echo    - Qdrant vector database   (vector_store\, storage\, snapshots\)
echo    - Application logs         (logs\)
echo.
echo  *** MONGODB DATA IS COMPLETELY SAFE ***
echo  The following are NEVER touched by this script:
echo    - Leads (visitor contact details)
echo    - Chat logs
echo    - Visitor records
echo    - Bookings
echo    - Any other MongoDB collection
echo.
echo  Source code, .env, virtual environment, and
echo  application settings are also kept untouched.
echo.
set /p "CONFIRM=Type RESET to delete vector DB + uploads + logs (MongoDB kept safe): "
if /I not "%CONFIRM%"=="RESET" (
    echo.
    echo  Reset cancelled. Nothing was deleted.
    exit /b 0
)

echo.
echo  Stopping DocMind services...
call "%ROOT%stop_servers.bat" >nul 2>&1
timeout /t 3 /nobreak >nul

echo  Removing uploads, vector data, snapshots, and logs...

:: Delete each folder entirely, then recreate it (including required sub-folders)
for %%D in ("%ROOT%uploads" "%ROOT%vector_store" "%ROOT%storage" "%ROOT%logs") do (
    if exist "%%~D" rmdir /s /q "%%~D"
    mkdir "%%~D" >nul 2>&1
)

:: snapshots needs its tmp\upload sub-folder recreated for the app to work
if exist "%ROOT%snapshots" rmdir /s /q "%ROOT%snapshots"
mkdir "%ROOT%snapshots\tmp\upload" >nul 2>&1

echo.
echo  ==========================================
echo   Reset complete.
echo   Vector DB, uploads, and logs cleared.
echo   MongoDB leads and chat data: UNTOUCHED.
echo   Run start_servers.bat to start fresh.
echo  ==========================================
echo.
pause
exit /b 0
