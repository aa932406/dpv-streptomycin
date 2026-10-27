@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo [ERROR] Python 3.10+ not found.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

echo Using Python: %PY%
%PY% scripts\launch_web.py %*
if errorlevel 1 (
  echo.
  echo [ERROR] Startup failed. Read the messages above.
  pause
  exit /b 1
)
endlocal
