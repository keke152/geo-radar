@echo off
cd /d "%~dp0"
start "Thesis Copilot - Python" cmd /k call start-python.bat
start "Thesis Copilot - Java" cmd /k call start-java.bat
start "Thesis Copilot - Frontend" cmd /k call start-frontend.bat
echo Starting the demo services. Open http://127.0.0.1:5173 after the frontend is ready.
