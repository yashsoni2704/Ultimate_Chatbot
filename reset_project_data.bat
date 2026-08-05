@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PYTHON=%ROOT%Yash\Scripts\python.exe"

title DocMind - Reset Project Data
echo.
echo  ==========================================
echo   DocMind - Reset All Project Runtime Data
echo  ==========================================
echo.
echo  This permanently removes:
echo    - uploaded files
echo    - Qdrant vector database data
echo    - legacy vector data and snapshots
echo    - application logs
echo    - all data in the MongoDB database configured in .env
echo.
echo  Source code, .env, virtual environment, and application settings are kept.
echo.
set /p "CONFIRM=Type RESET to permanently delete this data: "
if /I not "%CONFIRM%"=="RESET" (
    echo.
    echo  Reset cancelled. Nothing was deleted.
    exit /b 0
)

if not exist "%PYTHON%" (
    echo.
    echo  ERROR: Python was not found at: %PYTHON%
    exit /b 1
)

echo.
echo  Stopping DocMind services...
call "%ROOT%stop_servers.bat"

echo  Removing uploads, vector data, snapshots, and logs...
for %%D in ("%ROOT%uploads" "%ROOT%vector_store" "%ROOT%storage" "%ROOT%snapshots" "%ROOT%logs") do (
    if exist "%%~D" rmdir /s /q "%%~D"
    mkdir "%%~D" >nul 2>&1
)

echo  Resetting the configured MongoDB database...
pushd "%ROOT%"
"%PYTHON%" -c "from pymongo import MongoClient; from config import Config; client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=5000); client.admin.command('ping'); client.drop_database(Config.MONGO_DB_NAME); client.close(); print('  MongoDB database reset: ' + Config.MONGO_DB_NAME)"
set "MONGO_RESULT=%ERRORLEVEL%"
popd

if not "%MONGO_RESULT%"=="0" (
    echo.
    echo  WARNING: Local files were reset, but MongoDB could not be reset.
    echo  Check that MongoDB is running and that MONGO_URI in .env is correct.
    exit /b %MONGO_RESULT%
)

echo.
echo  ==========================================
echo   Reset complete. Run start_servers.bat to start fresh.
echo  ==========================================
echo.
exit /b 0
