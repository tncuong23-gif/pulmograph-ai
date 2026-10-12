@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-vieneu\Scripts\python.exe" (
  call setup_vieneu_windows.bat
  if errorlevel 1 exit /b 1
)
echo Installing CUDA support only in .venv-vieneu. Backend venv is unchanged.
".venv-vieneu\Scripts\python.exe" -m pip freeze > vieneu-before-gpu.txt
".venv-vieneu\Scripts\python.exe" -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 exit /b 1
".venv-vieneu\Scripts\python.exe" -m pip install "vieneu[cuda]==3.8.3" "transformers==4.57.6"
if errorlevel 1 exit /b 1
".venv-vieneu\Scripts\python.exe" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable: check NVIDIA driver and torch installation'; print(torch.cuda.get_device_name(0)); print('Free/total VRAM bytes:', torch.cuda.mem_get_info())"
if errorlevel 1 exit /b 1
echo Ready. Stop the old VieNeu server, then run start_vieneu_gpu_windows.bat.
