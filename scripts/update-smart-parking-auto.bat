@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-smart-parking.ps1" -Yes %*
pause
