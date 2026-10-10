@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" setup
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" setup
:done
if errorlevel 1 (
  echo Setup failed. Install Python 3.12 x64 and retry. See messages above.
  pause
  exit /b 2
)
echo Setup complete. Open Launch-TBS.cmd.
pause
