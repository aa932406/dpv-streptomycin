@echo off
chcp 65001 >nul
setlocal

REM ---------------------------------------------------------------------------
REM  Calibration run.  Needs metadata\metadata.csv with concentration_M filled.
REM  Copy metadata\sample_metadata_template.csv to metadata\metadata.csv first.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] run run_all.bat once first -- it creates .venv and installs deps.
    pause
    exit /b 1
)

if not exist "metadata\metadata.csv" (
    echo [ERROR] metadata\metadata.csv not found.
    echo         copy metadata\sample_metadata_template.csv metadata\metadata.csv
    echo         then fill in the concentration_M column.
    pause
    exit /b 1
)

echo Running ratiometric calibration ...
".venv\Scripts\python.exe" "scripts\ratiometric_calibration.py" --meta "metadata\metadata.csv"
if errorlevel 1 goto :fail

echo.
echo Done. Results are in out\^<date^>\ :
echo   figures\fig9_calibration.png
echo   ratiometric_report.json
pause
exit /b 0

:fail
echo.
echo [ERROR] see the message above.
pause
exit /b 1
