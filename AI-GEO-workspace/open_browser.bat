@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start.bat once to prepare the Python environment.
  pause
  exit /b 1
)
.venv\Scripts\python.exe start_desktop.py --browser
