@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe desktop_service.py --disable-autostart
) else (
  python desktop_service.py --disable-autostart
)
echo Login auto-start removed and background stop requested.
echo Run start.bat to enable it again.
pause
