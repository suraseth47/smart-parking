@echo off
REM ============================================================
REM  Smart Parking - open SERVER admin via SSH tunnel (port 9000)
REM  Double-click > type your SSH username + password > browser opens admin page
REM  Close this window (or Ctrl+C) when done to disconnect
REM ============================================================
chcp 65001 >nul
title Smart Parking - Server (SSH tunnel :9000)

set HOST=192.168.200.196
set URL=http://localhost:9000/admin/login

REM ถ้ามี tunnel เปิดอยู่แล้ว ไม่ต้องเปิดซ้ำ แค่เปิดเบราว์เซอร์
netstat -ano | findstr /R /C:":9000 .*LISTENING" >nul
if not errorlevel 1 (
    echo มีการเชื่อมต่อ Server เปิดอยู่แล้ว กำลังเปิดหลังบ้าน...
    start "" %URL%
    timeout /t 3 >nul
    exit /b 0
)

REM ถามชื่อผู้ใช้ SSH ของแต่ละคน (จำไว้ในเครื่องสำหรับครั้งถัดไป)
set USERFILE=%USERPROFILE%\.smart-parking-ssh-user
set SSHUSER=
if exist "%USERFILE%" set /p SSHUSER=<"%USERFILE%"
if "%SSHUSER%"=="" (
    set /p SSHUSER=ชื่อผู้ใช้ SSH ของคุณบน Server: 
) else (
    echo ชื่อผู้ใช้ SSH: %SSHUSER%   ^(ถ้าจะเปลี่ยน ให้ลบไฟล์ %USERFILE%^)
)
if "%SSHUSER%"=="" (
    echo ต้องใส่ชื่อผู้ใช้
    pause
    exit /b 1
)
>"%USERFILE%" echo %SSHUSER%
set SERVER=%SSHUSER%@%HOST%

REM รอจนเชื่อมต่อสำเร็จ (หลังใส่รหัสผ่าน) แล้วค่อยเปิดเบราว์เซอร์ให้อัตโนมัติ
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "$t=0; while(-not (Get-NetTCPConnection -LocalPort 9000 -State Listen -ErrorAction SilentlyContinue) -and $t -lt 180){Start-Sleep 1; $t++}; if($t -lt 180){Start-Process '%URL%'}"

echo ============================================================
echo  กำลังเชื่อมต่อ Server %SERVER%
echo  1) ใส่รหัสผ่าน SSH ของ %SSHUSER% (ตัวอักษรจะไม่ขึ้นบนจอ เป็นเรื่องปกติ)
echo  2) เบราว์เซอร์จะเปิด %URL% ให้เอง
echo  3) ห้ามปิดหน้าต่างนี้ระหว่างใช้งานหลังบ้าน
echo ============================================================
ssh -N -o ServerAliveInterval=60 -L 9000:127.0.0.1:8000 %SERVER%

echo.
echo การเชื่อมต่อ Server ถูกปิดแล้ว
pause
