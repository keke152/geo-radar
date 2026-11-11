@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto install
py -3.10 -m venv .venv
if not errorlevel 1 goto install
python -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,14)"
if errorlevel 1 goto failed
python -m venv .venv
if errorlevel 1 goto failed
:install
.venv\Scripts\python.exe -c "import fastapi,uvicorn,httpx,multipart,dotenv,playwright.async_api" >nul 2>&1
if not errorlevel 1 goto launch
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
echo Starting AI GEO at http://127.0.0.1:8020 ...
.venv\Scripts\python.exe start_desktop.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup failed. Install Python 3.10-3.13 and Microsoft Edge, then retry.
pause
exit /b 1
