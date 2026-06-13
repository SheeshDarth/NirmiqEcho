@echo off
title Nirmiq Echo - Setup
echo.
echo  Nirmiq Echo - local-first voice OS setup
echo  ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11+ from python.org
    pause & exit /b 1
)

echo  [1/3] Installing Python backend (editable)...
pip install -e . --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause & exit /b 1
)

echo  [2/3] Checking Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
    echo  [WARN] Ollama not found. Install from https://ollama.com
    echo         The planner needs a local model, e.g.: ollama pull qwen3.5:4b
) else (
    echo  [OK] Ollama present. Models:
    ollama list
)

echo  [3/3] Running core tests...
python -m pytest tests/test_core.py -q

echo.
echo  Setup complete. Start the backend with:
echo     python -m core.main
echo.
pause
