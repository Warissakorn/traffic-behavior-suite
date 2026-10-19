@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" setup --detection --accelerator cuda
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" setup --detection --accelerator cuda
:done
if errorlevel 1 (
  echo NVIDIA CUDA setup failed. See messages above.
  pause
  exit /b 2
)
echo CUDA runtime installed. Select auto or GPU 0 in the GUI.
echo A compatible NVIDIA driver and GPU are required for GPU inference.
pause
exit /b 0
