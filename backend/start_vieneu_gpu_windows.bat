@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-vieneu\Scripts\python.exe" (
  echo Run setup_vieneu_gpu_windows.bat first.
  exit /b 1
)
".venv-vieneu\Scripts\python.exe" -c "import torch; assert torch.cuda.is_available(), 'Run setup_vieneu_gpu_windows.bat first'; print('VieNeu GPU:', torch.cuda.get_device_name(0)); print('Free/total VRAM bytes:', torch.cuda.mem_get_info())"
if errorlevel 1 exit /b 1
set "HOST=127.0.0.1"
set "PORT=8880"
set "VIENEU_BACKEND=pytorch"
set "VIENEU_DEVICE=cuda"
set "VIENEU_MAX_STREAMS=2"
echo Keep this window open. Wait for Application startup complete.
".venv-vieneu\Scripts\python.exe" -m apps.openai_speech
