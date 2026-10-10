@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3.12 "%~dp0tools\windows\bootstrap.py" test
goto done
:pythonfallback
python "%~dp0tools\windows\bootstrap.py" test
:done
if errorlevel 1 (
  echo Windows test FAILED. See diagnostics above.
  pause
  exit /b 2
)
echo Windows test PASS.
pause
exit /b 0
