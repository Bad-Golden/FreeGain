@echo off
rem Builds dist\FreeGain.exe -- a single standalone file that runs without
rem Python installed. Needs Python 3.10+ on the build machine only.
cd /d "%~dp0\.."

py -3 -m venv .build-venv 2>nul || python -m venv .build-venv
".build-venv\Scripts\python.exe" -m pip install --upgrade pip
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean packaging\freegain.spec
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Built dist\FreeGain.exe
pause
