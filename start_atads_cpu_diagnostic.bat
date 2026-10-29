@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ATADS - CPU diagnostic mode
set "ATADS_DEVICE=cpu"
echo Dang chay CPU che do chan doan theo lua chon rieng.
echo Inference CPU co the rat cham; khong dung de danh gia FPS thoi gian thuc.
call "%~dp0start_atads.bat"
