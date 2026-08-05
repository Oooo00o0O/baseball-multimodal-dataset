@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0merge_team_results.ps1" %*
if errorlevel 1 pause
