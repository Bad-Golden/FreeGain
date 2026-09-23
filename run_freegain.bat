@echo off
rem Double-click to run FreeGain on Windows. The first run creates a local
rem virtual environment (.venv) and installs the requirements into it.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up FreeGain for the first time...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create a Python environment. Install Python 3.10+ from
        echo python.org and tick "Add python.exe to PATH" during install.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Installing requirements failed -- check your internet connection.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" freegain_app.py
if errorlevel 1 pause
