@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-clinical\Scripts\python.exe" (
  py -3.12 -m venv .venv-clinical
  if errorlevel 1 exit /b 1
)
set "CLINICAL_PYTHON=%CD%\.venv-clinical\Scripts\python.exe"
"%CLINICAL_PYTHON%" -m pip install -r clinical_service\requirements-api.txt
if errorlevel 1 exit /b 1
pushd clinical_service\vendor\clinical-ie
"%CLINICAL_PYTHON%" -m pip install -r requirements.txt -r requirements-vision.txt
if errorlevel 1 (
  popd
  exit /b 1
)
popd
"%CLINICAL_PYTHON%" -m pip check
if errorlevel 1 exit /b 1
"%CLINICAL_PYTHON%" -m scripts.check_clinical_assets
if errorlevel 1 (
  echo Thieu hoac sai checksum model. Xem CLINICAL_MULTIMODAL_UPDATE_VI.md truoc khi chay TXT.
  exit /b 2
)
echo Cai dat Clinical IE hoan tat. Chay start_clinical_windows.bat.
