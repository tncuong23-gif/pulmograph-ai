@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo Copy .env.example to .env and configure database connections first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
pause
