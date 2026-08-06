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
echo    - uploaded files
echo    - Qdrant vector database data (storage, snapshots)
echo    - application logs
echo.
echo  MongoDB data is NOT touched.
echo  Source code, .env, virtual environment, and application settings are kept.
echo.
set /p "CONFIRM=Type RESET to permanently delete this data: "
if /I not "%CONFIRM%"=="RESET" (
    echo.
    echo  Reset cancelled. Nothing was deleted.
    exit /b 0
)

echo.
echo  Stopping DocMind services...
call "%ROOT%stop_servers.bat"

echo  Removing uploads, vector data, snapshots, and logs...
for %%D in ("%ROOT%uploads" "%ROOT%vector_store" "%ROOT%storage" "%ROOT%snapshots" "%ROOT%logs") do (
    if exist "%%~D" rmdir /s /q "%%~D"
    mkdir "%%~D" >nul 2>&1
)

echo.
echo  ==========================================
echo   Reset complete. Run start_servers.bat to start fresh.
echo  ==========================================
echo.
exit /b 0
