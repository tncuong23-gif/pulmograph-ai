@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-vieneu\Scripts\python.exe" (
  py -3.12 -m venv .venv-vieneu
  if errorlevel 1 (
    echo Install Python 3.12, then run this script again.
    exit /b 1
  )
)
".venv-vieneu\Scripts\python.exe" -m pip install -r requirements-vieneu.txt
if errorlevel 1 (
  echo Installation failed. Check the pip error above.
  exit /b 1
)
echo Installed separately. Update backend .env using VOICE_VIENEU_GUIDE_VI.md.
echo Run start_vieneu_windows.bat and wait for Application startup complete.
