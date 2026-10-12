@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-vieneu\Scripts\python.exe" (
  echo Run setup_vieneu_windows.bat first.
  exit /b 1
)
set "HOST=127.0.0.1"
set "PORT=8880"
if not defined VIENEU_BACKEND set "VIENEU_BACKEND=onnx"
if not defined VIENEU_DEVICE set "VIENEU_DEVICE=cpu"
if not defined VIENEU_PRECISION set "VIENEU_PRECISION=fp32"
if not defined VIENEU_MAX_STREAMS set "VIENEU_MAX_STREAMS=1"
echo Starting local VieNeu on http://127.0.0.1:8880
echo First start downloads model weights. Keep this window open.
".venv-vieneu\Scripts\python.exe" -m apps.openai_speech
if errorlevel 1 exit /b 1
