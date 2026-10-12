@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Python 3.12 is needed by this setup script. Python 3.11+ can also be used manually.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
if not exist ".env" copy ".env.example" ".env" >nul
echo Edit .env with your existing database URIs and passwords, then run run_backend.bat.
pause
