@echo off
chcp 65001 >nul
rem Apply update zip in one click: extract to project - update Server - git commit - git push
rem Double-click = use the newest update zip / drag a zip onto this file = use that zip
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply-update-smart-parking.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply-update-smart-parking.ps1" -Zip "%~1"
)
pause
