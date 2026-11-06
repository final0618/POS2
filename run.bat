@echo off
setlocal
cd /d "%~dp0"

if not defined PORT set "PORT=8001"

if not exist ".venv\Scripts\python.exe" (
    echo Error: project virtual environment was not found at .venv\Scripts\python.exe
    exit /b 1
)

echo Starting Good Morning Club API at http://127.0.0.1:%PORT%
".venv\Scripts\python.exe" -m uvicorn src.main:app --host 127.0.0.1 --port %PORT%
exit /b %errorlevel%
