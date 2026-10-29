@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ATADS - PyTorch CUDA update
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [LOI] Khong tim thay .venv. Tao moi truong truoc.
  pause
  exit /b 1
)
echo Script nay se thay PyTorch hien tai trong .venv bang wheel CUDA 13.0.
echo Khong chay neu ban muon giu nguyen moi truong. Script khong sua checkpoint.
echo Lenh chinh thuc PyTorch: torch 2.12.0, torchvision 0.27.0, CUDA 13.0.
set "CONFIRM="
set /p "CONFIRM=Nhap INSTALL de tiep tuc: "
if /i not "%CONFIRM%"=="INSTALL" (
  echo Da huy. Moi truong khong bi thay doi.
  pause
  exit /b 0
)
"%PYTHON%" -m pip install --upgrade torch==2.12.0 torchvision==0.27.0 --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 (
  echo [LOI] Cai PyTorch that bai. Kiem tra ket noi, Python 64-bit va dung luong dia.
  pause
  exit /b 1
)
"%PYTHON%" -m backend.utils.gpu_check
if errorlevel 1 (
  echo [LOI] Wheel da cai nhung chua xac nhan ho tro GPU. Xem thong tin phia tren.
  pause
  exit /b 1
)
echo PyTorch CUDA moi da qua kiem tra architecture. Hay chay start_atads.bat.
pause
