@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ATADS - Automatic Traffic Accident Detection System
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10-3.12 hoac tao .venv.
    pause
    exit /b 1
  )
  set "PYTHON=python"
)
"%PYTHON%" -c "import fastapi,uvicorn,torch,ultralytics,cv2; print('Dependencies OK')"
if errorlevel 1 (
  echo [LOI] Thieu dependency. Xem README.md; khong tu dong thay PyTorch/CUDA.
  pause
  exit /b 1
)
if not exist "runs\detect\phuong_tien\huan_luyen\weights\best.pt" (
  echo [LOI] Khong tim thay model phuong tien. Sua config\settings.json.
  pause
  exit /b 1
)
if not exist "runs\detect\yolo_v11_small_accident\huan_luyen\weights\best.pt" (
  echo [LOI] Khong tim thay model tai nan. Sua config\settings.json.
  pause
  exit /b 1
)
"%PYTHON%" -m backend.utils.gpu_check
if errorlevel 1 (
  echo [LOI] CUDA cua moi truong hien tai khong tuong thich voi GPU.
  echo Chay install_cuda_pytorch.bat neu ban chap nhan cap nhat PyTorch.
  echo De kiem tra dashboard bang CPU, chay start_atads_cpu_diagnostic.bat.
  pause
  exit /b 1
)
set "ATADS_PORT=8765"
netstat -ano | findstr /R /C:":%ATADS_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [LOI] Cong %ATADS_PORT% dang duoc su dung. Kiem tra ung dung khac.
  pause
  exit /b 1
)
echo Dang nap model va khoi dong ATADS tren device da cau hinh.
start "ATADS readiness" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait_for_atads.ps1" -Port %ATADS_PORT%
"%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port %ATADS_PORT% --log-level info
if errorlevel 1 echo [LOI] ATADS dung do startup/inference gap loi. Doc terminal va data\logs\atads.log.
echo ATADS da dung. Dong cua so nay de ket thuc backend.
pause
