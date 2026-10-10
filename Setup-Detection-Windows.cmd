@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" setup --detection
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" setup --detection
:done
if errorlevel 1 (
  echo Detection setup failed. See messages above.
  pause
  exit /b 2
)
echo Detection setup complete. Choose your local model weights in the GUI.
pause
