@echo off
rem Runs FreeGain from source on Windows. The first run creates a local
rem virtual environment (.venv) and installs the requirements into it.
rem
rem Don't want to install Python? Use FreeGain.exe instead -- it has
rem everything built in. See README.md, "Download (no install needed)".
cd /d "%~dp0"
set "VENV_PY=.venv\Scripts\python.exe"
set "MARKER=.venv\freegain-installed.txt"

rem Double-clicking this file inside a zip in Explorer runs a lone copy
rem from a temp folder, so the rest of FreeGain isn't next to it.
if not exist "freegain_app.py" goto not_extracted
if not exist "requirements.txt" goto not_extracted

rem Setup is only finished once the marker exists, so a failed or
rem interrupted install is retried on the next run instead of skipped.
if exist "%MARKER%" goto run

echo Setting up FreeGain for the first time. This needs an internet
echo connection and takes a minute or two...
echo.

if exist ".venv" rmdir /s /q ".venv"

rem Prefer the "py" launcher that python.org installs, else "python".
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import sys" >nul 2>&1
if not errorlevel 1 goto use_python
goto no_python
:use_py
set "PYEXE=py"
set "PYARG=-3"
goto have_python
:use_python
set "PYEXE=python"
set "PYARG="
:have_python

%PYEXE% %PYARG% -c "import sys, struct; print('Using Python', sys.version.split()[0], '(%%d-bit)' %% (struct.calcsize('P') * 8))"
%PYEXE% %PYARG% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto old_python

%PYEXE% %PYARG% -m venv .venv
if errorlevel 1 goto venv_failed

"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install --prefer-binary -r requirements.txt
if errorlevel 1 (
    echo.
    echo Retrying once...
    "%VENV_PY%" -m pip install --prefer-binary --retries 10 --timeout 60 -r requirements.txt
    if errorlevel 1 goto install_failed
)
echo ok> "%MARKER%"

:run
"%VENV_PY%" freegain_app.py
if errorlevel 1 pause
exit /b

:no_python
echo Python was not found.
goto suggest_exe

:old_python
echo This Python is too old -- FreeGain needs Python 3.10 or newer.
goto suggest_exe

:not_extracted
echo FreeGain's files aren't next to this script. This usually means it
echo was opened from inside a zip file.
echo.
echo Fix: close this window, right-click the zip, choose "Extract All...",
echo then open the extracted folder and double-click run_freegain.bat.
echo.
pause
exit /b 1

:venv_failed
echo Could not create a Python environment in this folder.
echo If the folder is inside a zip file, extract it first.
goto suggest_exe

:install_failed
echo.
echo ================================================================
echo  Installing the required packages failed. The real reason is in
echo  the text above (look for lines starting with "ERROR").
echo  Common causes: no internet, a school/work network or firewall
echo  blocking pypi.org, or antivirus blocking the download.
echo ================================================================
if exist ".venv" rmdir /s /q ".venv"
goto suggest_exe

:suggest_exe
echo.
echo EASIEST FIX: use FreeGain.exe instead. It needs no Python and no
echo downloads. Get FreeGain-Windows.zip, extract it, and double-click
echo FreeGain.exe.
echo.
pause
exit /b 1
