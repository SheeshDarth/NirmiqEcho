@echo off
title NirmiqEcho Setup
echo ===================================================
echo        NirmiqEcho - Automated Setup
echo ===================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Python found:
python --version
echo.

echo [2/3] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo.

echo [3/3] Installing dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Some packages may have failed. Check output above.
)

echo.
echo ===================================================
echo   Setup complete!
echo.
echo   To run NirmiqEcho:
echo     python main.py
echo.
echo   For GPU support (NVIDIA only):
echo     pip install torch --index-url https://download.pytorch.org/whl/cu121
echo ===================================================
echo.
pause
