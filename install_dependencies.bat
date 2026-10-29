@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.10 -m venv .venv
  if errorlevel 1 exit /b 1
)
echo Bao toan PyTorch/CUDA hien co. Cai dependency web/runtime con lai.
.venv\Scripts\python.exe -m pip install fastapi==0.143.0 "uvicorn[standard]==0.54.0" python-multipart==0.0.20 ultralytics==8.4.160 opencv-python==5.0.0.0 psutil==7.0.0
if errorlevel 1 echo Cai dat that bai. Neu can PyTorch CUDA, cai wheel tuong thich rieng theo README.
pause
