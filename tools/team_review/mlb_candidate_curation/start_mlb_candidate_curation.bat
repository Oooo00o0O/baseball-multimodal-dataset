@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_mlb_candidate_curation.ps1" %*
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" (
  echo.
  echo Startup failed. See the Chinese error message above.
  pause
)
exit /b %exit_code%
