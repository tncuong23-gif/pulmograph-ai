@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-clinical\Scripts\python.exe" (
  echo Chua co .venv-clinical. Xem CLINICAL_MULTIMODAL_UPDATE_VI.md.
  exit /b 1
)
".venv-clinical\Scripts\python.exe" -m uvicorn clinical_service.app:app --host 127.0.0.1 --port 8002 --workers 1
