@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" launch --debug
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" launch --debug
:done
pause
