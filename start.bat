@echo off
setlocal
title browser launcher v2
cd /d "%~dp0"

rem ---- find Python (python, then py) -------------------------------------
set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if "%PY%"=="" (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)
if "%PY%"=="" (
    echo.
    echo  [X] Python 3.10+ was not found on this computer.
    echo.
    echo      Install it from https://www.python.org/downloads/
    echo      and tick "Add python.exe to PATH" during setup.
    echo.
    echo  (launcher v2)
    pause
    exit /b 1
)

rem ---- check dependencies -------------------------------------------------
%PY% -c "import PyQt6, cryptography" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Dependencies are missing. Installing them now:
    echo    PyQt6  PyQt6-WebEngine  cryptography
    echo.
    %PY% -m pip install PyQt6 PyQt6-WebEngine cryptography
    if errorlevel 1 (
        echo.
        echo  [X] Could not install dependencies automatically.
        echo      Run this manually and check for errors:
        echo          %PY% -m pip install PyQt6 PyQt6-WebEngine cryptography
        echo.
        echo  (launcher v2)
        pause
        exit /b 1
    )
)

rem ---- launch --------------------------------------------------------------
echo Starting browser...
%PY% main.py %*
set "RC=%ERRORLEVEL%"

rem ---- ALWAYS stop here so errors can be read ------------------------------
echo.
if "%RC%"=="0" (
    echo  browser closed normally.
) else if "%RC%"=="2" (
    echo  browser could not start here - reason shown above.
) else (
    echo  browser exited with code %RC%. Details above.
)
echo  (launcher v2 - if you see this line, the new launcher is running)
pause
exit /b 0
