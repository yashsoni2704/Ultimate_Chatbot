@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  DocMind — Post-Install Helper
::  Runs automatically after Inno Setup copies all app files.
::
::  Steps:
::   1. Create Python virtual environment (venv)
::   2. Upgrade pip
::   3. Install all pip packages from requirements.txt
::   4. Install Playwright browsers (Chromium)
::   5. Start Ollama service
::   6. Pull bge-m3 embedding model
::   7. Pull llama3.1 LLM model
::   8. Generate a secure SECRET_KEY in .env
::   9. Create uploads/, vector_store/, logs/ folders
:: ============================================================

set "INSTALL_DIR=%~1"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=C:\DocMind"

set "PYTHON=%INSTALL_DIR%\env\Scripts\python.exe"
set "PIP=%INSTALL_DIR%\env\Scripts\pip.exe"
set "LOG=%INSTALL_DIR\install_log.txt"

echo [%date% %time%] DocMind install_helper started > "%INSTALL_DIR%\install_log.txt"
echo Install directory: %INSTALL_DIR% >> "%INSTALL_DIR%\install_log.txt"

:: ── Step 1: Find Python 3.11+ ─────────────────────────────────────────────
echo.
echo [1/9] Locating Python...
echo [1/9] Locating Python... >> "%INSTALL_DIR%\install_log.txt"

set "SYS_PYTHON="
for /f "tokens=*" %%P in ('where python 2^>nul') do (
    if "!SYS_PYTHON!"=="" set "SYS_PYTHON=%%P"
)

if "!SYS_PYTHON!"=="" (
    echo ERROR: Python not found in PATH. >> "%INSTALL_DIR%\install_log.txt"
    echo ERROR: Python was not found. Please re-run the installer.
    exit /b 1
)

echo Found Python: !SYS_PYTHON! >> "%INSTALL_DIR%\install_log.txt"
echo    Found: !SYS_PYTHON!

:: ── Step 2: Create virtual environment ───────────────────────────────────
echo.
echo [2/9] Creating virtual environment...
echo [2/9] Creating virtual environment... >> "%INSTALL_DIR%\install_log.txt"

if exist "%INSTALL_DIR%\env\Scripts\python.exe" (
    echo    Virtual environment already exists — skipping creation.
    echo    venv already exists — skipped >> "%INSTALL_DIR%\install_log.txt"
) else (
    "!SYS_PYTHON!" -m venv "%INSTALL_DIR%\env"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment. >> "%INSTALL_DIR%\install_log.txt"
        echo ERROR: Could not create virtual environment.
        exit /b 1
    )
    echo    Created: %INSTALL_DIR%\env
    echo    venv created OK >> "%INSTALL_DIR%\install_log.txt"
)

:: ── Step 3: Upgrade pip ───────────────────────────────────────────────────
echo.
echo [3/9] Upgrading pip...
echo [3/9] Upgrading pip... >> "%INSTALL_DIR%\install_log.txt"

"%PYTHON%" -m pip install --upgrade pip --quiet
echo    pip upgraded >> "%INSTALL_DIR%\install_log.txt"

:: ── Step 4: Install all packages from requirements.txt ───────────────────
echo.
echo [4/9] Installing Python packages (this takes 5-15 minutes on first run)...
echo [4/9] Installing Python packages... >> "%INSTALL_DIR%\install_log.txt"
echo    Packages include: Flask, LangChain, Docling, torch, qdrant-client,
echo    pymongo, sentence-transformers, FlagEmbedding, playwright, and more.
echo    Please wait — do not close this window.
echo.

"%PIP%" install -r "%INSTALL_DIR%\requirements.txt" ^
    --timeout 300 ^
    --retries 5 ^
    --no-warn-script-location ^
    >> "%INSTALL_DIR%\install_log.txt" 2>&1

if errorlevel 1 (
    echo ERROR: Package installation failed. Check install_log.txt for details.
    echo ERROR: pip install failed >> "%INSTALL_DIR%\install_log.txt"
    exit /b 1
)
echo    All packages installed successfully.
echo    pip install completed OK >> "%INSTALL_DIR%\install_log.txt"

:: ── Step 5: Install Playwright Chromium browser ───────────────────────────
echo.
echo [5/9] Installing Playwright browser (Chromium for web scraping)...
echo [5/9] Installing Playwright Chromium... >> "%INSTALL_DIR%\install_log.txt"

"%PYTHON%" -m playwright install chromium >> "%INSTALL_DIR%\install_log.txt" 2>&1
if errorlevel 1 (
    echo    WARNING: Playwright browser install failed. Web scraping may not work.
    echo    WARNING: Playwright failed >> "%INSTALL_DIR%\install_log.txt"
) else (
    echo    Chromium installed.
    echo    Playwright OK >> "%INSTALL_DIR%\install_log.txt"
)

:: ── Step 6: Start Ollama service ──────────────────────────────────────────
echo.
echo [6/9] Starting Ollama service...
echo [6/9] Starting Ollama service... >> "%INSTALL_DIR%\install_log.txt"

:: Check if ollama is already running
curl -s http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    start /min "" ollama serve
    echo    Ollama service started.
    :: Wait for it to be ready
    timeout /t 5 /nobreak >nul
) else (
    echo    Ollama already running.
)
echo    Ollama service ready >> "%INSTALL_DIR%\install_log.txt"

:: ── Step 7: Pull bge-m3 embedding model ──────────────────────────────────
echo.
echo [7/9] Downloading embedding model: bge-m3 (~670 MB)...
echo    This is the model that understands your documents.
echo    Please wait...
echo [7/9] Pulling bge-m3... >> "%INSTALL_DIR%\install_log.txt"

ollama pull bge-m3 >> "%INSTALL_DIR%\install_log.txt" 2>&1
if errorlevel 1 (
    echo    WARNING: bge-m3 pull failed. Check install_log.txt.
    echo    WARNING: bge-m3 pull failed >> "%INSTALL_DIR%\install_log.txt"
) else (
    echo    bge-m3 ready.
    echo    bge-m3 OK >> "%INSTALL_DIR%\install_log.txt"
)

:: ── Step 8: Pull llama3.1 LLM model ──────────────────────────────────────
echo.
echo [8/9] Downloading AI model: llama3.1 (~4.7 GB)...
echo    This is the language model that answers questions.
echo    This may take 10-20 minutes depending on your internet speed.
echo    Please wait...
echo [8/9] Pulling llama3.1... >> "%INSTALL_DIR%\install_log.txt"

ollama pull llama3.1:latest >> "%INSTALL_DIR%\install_log.txt" 2>&1
if errorlevel 1 (
    echo    WARNING: llama3.1 pull failed. Check install_log.txt.
    echo    WARNING: llama3.1 pull failed >> "%INSTALL_DIR%\install_log.txt"
) else (
    echo    llama3.1 ready.
    echo    llama3.1 OK >> "%INSTALL_DIR%\install_log.txt"
)

:: ── Step 9: Create required folders + .env ───────────────────────────────
echo.
echo [9/9] Setting up application folders and configuration...
echo [9/9] Setting up folders... >> "%INSTALL_DIR%\install_log.txt"

:: Create folders the app needs at runtime
for %%D in (uploads vector_store logs snapshots\tmp\upload) do (
    if not exist "%INSTALL_DIR%\%%D" (
        mkdir "%INSTALL_DIR%\%%D"
        echo    Created: %%D
    )
)

:: Generate .env from .env.example if .env doesn't exist
if not exist "%INSTALL_DIR%\.env" (
    copy /Y "%INSTALL_DIR%\.env.example" "%INSTALL_DIR%\.env" >nul

    :: Generate a random SECRET_KEY using Python
    for /f "delims=" %%K in ('"%PYTHON%" -c "import secrets; print(secrets.token_hex(32))"') do (
        set "SECRETKEY=%%K"
    )

    :: Write SECRET_KEY into .env
    powershell -Command ^
        "(Get-Content '%INSTALL_DIR%\.env') -replace 'SECRET_KEY=', 'SECRET_KEY=!SECRETKEY!' | Set-Content '%INSTALL_DIR%\.env'"

    echo    .env created with secure SECRET_KEY.
    echo    .env created OK >> "%INSTALL_DIR%\install_log.txt"
) else (
    echo    .env already exists — not overwritten.
    echo    .env already exists >> "%INSTALL_DIR%\install_log.txt"
)

:: ── Done ──────────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   DocMind installation complete!
echo   Log saved to: %INSTALL_DIR%\install_log.txt
echo ============================================================
echo.
echo [%date% %time%] install_helper completed successfully >> "%INSTALL_DIR%\install_log.txt"

exit /b 0
