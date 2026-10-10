@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" launch
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" launch
:done
if errorlevel 1 (
  echo Launch failed. Run Setup-Windows.cmd or Launch-TBS-Debug.cmd.
  pause
  exit /b 2
)
