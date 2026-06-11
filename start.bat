@echo off
title NirmiqEcho
color 0B

echo.
echo  ███╗   ██╗██╗██████╗ ███╗   ███╗██╗ ██████╗
echo  ████╗  ██║██║██╔══██╗████╗ ████║██║██╔═══██╗
echo  ██╔██╗ ██║██║██████╔╝██╔████╔██║██║██║   ██║
echo  ██║╚██╗██║██║██╔══██╗██║╚██╔╝██║██║██║▄▄ ██║
echo  ██║ ╚████║██║██║  ██║██║ ╚═╝ ██║██║╚██████╔╝
echo  ╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚══▀▀═╝
echo              E C H O  v1.0
echo.

cd /d "%~dp0"

:: Check Python 3.11+
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11+ from python.org
    pause & exit /b 1
)

:: First-run: install dependencies
if not exist ".deps_ok" (
    echo  [SETUP] Installing dependencies — this may take a few minutes on first run...
    echo  [SETUP] Whisper large-v3 model already downloaded — no extra download needed.
    echo.
    pip install -r voiceflow_local\requirements.txt --quiet
    if errorlevel 1 (
        echo  [ERROR] Dependency install failed. Run: pip install -r voiceflow_local\requirements.txt
        pause & exit /b 1
    )
    echo. > .deps_ok
    echo  [SETUP] Dependencies installed.
)

:: Create .env if missing
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo  [INFO] Created .env - add your ANTHROPIC_API_KEY for complex commands.
)

echo  [INFO] Starting NirmiqEcho...
echo  [INFO] Look for the mic icon in your system tray.
echo  [INFO] Whisper model loads from local cache in ~2 seconds.
echo  [INFO] Press F9 to start/stop listening.
echo.

cd /d "%~dp0voiceflow_local"
python main.py

:: If it crashes, keep the window open to see the error
if errorlevel 1 (
    echo.
    echo  [ERROR] NirmiqEcho crashed. See error above.
    pause
)
