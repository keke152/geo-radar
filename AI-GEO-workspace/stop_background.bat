@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe desktop_service.py --stop
) else (
  python desktop_service.py --stop
)
echo Background stop requested. Login auto-start remains enabled.
pause
