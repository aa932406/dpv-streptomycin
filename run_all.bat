@echo off
chcp 65001 >nul
setlocal

REM ---------------------------------------------------------------------------
REM  One-click run: parses data\<date>\*.cor, writes to out\<date>\
REM  Put this file in the PROJECT ROOT (next to data\, scripts\, out\).
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found on PATH.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

echo [2/3] installing dependencies ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto :fail

echo [3/3] running the pipeline ...
".venv\Scripts\python.exe" "scripts\dpv_pipeline.py"
if errorlevel 1 goto :fail

echo.
echo Done. Results are in out\^<date^>\ :
echo   figures\fig1..fig6   publication figures
echo   dpv_features.csv      one row per curve
echo   report.json           all statistics
pause
exit /b 0

:fail
echo.
echo [ERROR] something went wrong above. Copy the last few lines if you need help.
pause
exit /b 1
