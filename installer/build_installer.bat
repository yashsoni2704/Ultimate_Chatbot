@echo off
setlocal EnableExtensions

:: ============================================================
::  DocMind — Build Installer
::  Double-click this to compile DocMind_Setup.exe
::
::  Requirements:
::    - Inno Setup 6 must be installed
::      Download: https://jrsoftware.org/isdl.php
::
::  Output:
::    installer\Output\DocMind_Setup.exe
:: ============================================================

title DocMind - Building Installer

echo.
echo  ==========================================
echo   DocMind - Building Installer
echo  ==========================================
echo.

:: ── Find Inno Setup compiler ─────────────────────────────────────────────
set "ISCC="

if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    goto :found_iscc
)

if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
    goto :found_iscc
)

:: Not found
echo  ERROR: Inno Setup 6 not found.
echo.
echo  Please download and install it from:
echo    https://jrsoftware.org/isdl.php
echo.
echo  Then run this script again.
echo.
pause
exit /b 1

:found_iscc
echo  Found Inno Setup: %ISCC%
echo.

:: ── Check icon exists, create placeholder if missing ─────────────────────
if not exist "%~dp0assets\DocMind.ico" (
    echo  NOTE: assets\DocMind.ico not found.
    echo  Using default icon. To use a custom icon, place DocMind.ico in installer\assets\
    echo.
    :: Create a minimal valid .ico by copying a system icon
    copy /Y "%SystemRoot%\System32\shell32.dll" "%~dp0assets\DocMind.ico" >nul 2>&1
    :: Better: extract from shell32 using PowerShell
    powershell -NoProfile -Command ^
        "$icon = [System.Drawing.Icon]::ExtractAssociatedIcon('%SystemRoot%\System32\cmd.exe'); $icon.ToBitmap().Save('%~dp0assets\DocMind_tmp.png'); " ^
        2>nul
    :: Fallback: just copy a known ico file
    for %%I in ("%SystemRoot%\System32\*.ico") do (
        copy /Y "%%I" "%~dp0assets\DocMind.ico" >nul 2>&1
        goto :icon_done
    )
    :icon_done
)

:: ── Check all required source files exist ────────────────────────────────
echo  Checking source files...
set "SRC=%~dp0.."
set "MISSING=0"

for %%F in (app.py admin_app.py config.py watcher.py requirements.txt .env.example qdrant.exe) do (
    if not exist "%SRC%\%%F" (
        echo  WARNING: Source file missing: %%F
        set "MISSING=1"
    )
)

for %%D in (utils db static templates) do (
    if not exist "%SRC%\%%D" (
        echo  WARNING: Source folder missing: %%D
        set "MISSING=1"
    )
)

if "%MISSING%"=="1" (
    echo.
    echo  Some source files are missing. The installer may be incomplete.
    echo  Continue anyway? Press any key or Ctrl+C to cancel.
    pause >nul
)

echo  All source files found.
echo.

:: ── Create Output folder ─────────────────────────────────────────────────
if not exist "%~dp0Output" mkdir "%~dp0Output"

:: ── Compile ──────────────────────────────────────────────────────────────
echo  Compiling DocMind_Setup.iss...
echo  This takes about 30-60 seconds...
echo.

"%ISCC%" "%~dp0DocMind_Setup.iss"

if errorlevel 1 (
    echo.
    echo  ==========================================
    echo   BUILD FAILED
    echo   Check the errors above.
    echo  ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   BUILD SUCCESSFUL
echo   Output: installer\Output\DocMind_Setup.exe
echo  ==========================================
echo.
echo  You can now share DocMind_Setup.exe with anyone.
echo.

:: Open the Output folder
explorer "%~dp0Output"

pause
exit /b 0
