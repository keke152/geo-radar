@echo off
cd /d "%~dp0python-service"
if not exist .venv\Scripts\python.exe py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
set JAVA_AUTH_URL=http://127.0.0.1:8081
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
