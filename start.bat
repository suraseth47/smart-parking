@echo off
REM ============================================================
REM  Smart Parking - start web + worker (Windows, development)
REM  Double-click this file to start. Close the 2 windows to stop.
REM ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found in %CD%
    echo Create it first: python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo [1/3] Updating database (alembic upgrade head)...
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] Database migration failed. See the message above.
    pause
    exit /b 1
)

echo [2/3] Starting WEB  (http://localhost:8000) ...
start "Smart Parking - WEB" cmd /k .venv\Scripts\python.exe -m uvicorn web.main:app --host 0.0.0.0 --port 8000

echo [3/3] Starting WORKER (camera + AI) ...
start "Smart Parking - WORKER" cmd /k .venv\Scripts\python.exe -m worker.main

echo Waiting for web to start...
timeout /t 5 /nobreak >nul
start "" http://localhost:8000/admin/login

echo.
echo Smart Parking is running in 2 windows: WEB and WORKER.
echo To stop: close both windows (or press Ctrl+C in each).
timeout /t 5 >nul
