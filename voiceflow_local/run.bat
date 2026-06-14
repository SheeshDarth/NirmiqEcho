@echo off
title NirmiqEcho
cd /d "%~dp0"
echo ===================================================
echo        NirmiqEcho - Voice Typing (Offline)
echo ===================================================
echo.
echo Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Starting NirmiqEcho...
echo Press F9 to start/stop listening. Close the window to quit.
echo.
python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] NirmiqEcho crashed. Check the output above.
    echo If dependencies are missing, run setup.bat first.
    pause
)
