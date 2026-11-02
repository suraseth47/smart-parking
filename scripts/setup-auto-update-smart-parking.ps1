# ตั้งโหมด "อัปเดตอัตโนมัติ" ของ Smart Parking ครั้งเดียว: ต่อไป update-smart-parking.bat จะไม่ถามรหัสผ่าน
#   1) สร้างกุญแจ SSH บนโน้ตบุ๊ก (ใช้กุญแจเดียวกับ CCTV Manager ถ้ามีแล้ว)
#   2) ฝากกุญแจไว้ที่ Server (ถามรหัสผ่าน SSH ครั้งสุดท้าย)
#   3) ถ้าผู้ใช้ไม่ได้อยู่ในกลุ่ม docker: อนุญาตให้รัน "เฉพาะคำสั่งอัปเดต" /usr/local/sbin/sp-upgrade ด้วย sudo โดยไม่ถามรหัส
# ⚠ ใครได้ไฟล์กุญแจ %USERPROFILE%\.ssh\id_ed25519 ของโน้ตบุ๊กนี้ จะเข้า Server และสั่งอัปเดตได้ → ห้ามคัดลอกไปที่อื่น
# ยกเลิก: .\setup-auto-update-smart-parking.bat -Remove
param(
  [string]$Server = '192.168.200.196',
  [string]$User = '',
  [switch]$Remove
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function Quiet([scriptblock]$b) { $o = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { & $b 2>$null } catch { $null } finally { $ErrorActionPreference = $o } }
$userFile = Join-Path $env:USERPROFILE '.smart-parking-ssh-user'
if (-not $User -and (Test-Path $userFile)) { $User = (Get-Content $userFile -Raw).Trim() }
if (-not $User) { $User = (Read-Host 'ชื่อผู้ใช้ SSH ของคุณบน Server').Trim(); if (-not $User) { exit 1 }; Set-Content -Path $userFile -Value $User -Encoding ASCII }
$t = "$User@$Server"
$key = Join-Path $env:USERPROFILE '.ssh\id_ed25519'
$up = Split-Path $PSScriptRoot -Parent
$sh = if (Test-Path (Join-Path $up 'scripts\sp-upgrade.sh')) { Join-Path $up 'scripts\sp-upgrade.sh' } else { 'D:\Naslink\Smart-Parking\scripts\sp-upgrade.sh' }

if ($Remove) {
  $pub = if (Test-Path "$key.pub") { (Get-Content "$key.pub" -Raw).Trim() } else { '' }
  & ssh -t $t "sudo rm -f /etc/sudoers.d/smart-parking-upgrade; if [ -n '$pub' ]; then grep -vxF '$pub' ~/.ssh/authorized_keys > ~/.ssh/ak.tmp; mv ~/.ssh/ak.tmp ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; fi; echo ยกเลิกแล้ว"
  exit 0
}
if (-not (Test-Path $sh)) { Write-Host "ไม่พบ $sh" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $key)) {
  Write-Host 'สร้างกุญแจ SSH — เมื่อถาม passphrase ให้กด Enter 2 ครั้ง (ไม่ตั้งรหัส)' -ForegroundColor Yellow
  New-Item -ItemType Directory -Force (Split-Path $key) | Out-Null
  & ssh-keygen -t ed25519 -f $key -C "cctv-update@$env:COMPUTERNAME"
  if (-not (Test-Path "$key.pub")) { Write-Host 'สร้างกุญแจไม่สำเร็จ' -ForegroundColor Red; exit 1 }
}
$pub = (Get-Content "$key.pub" -Raw).Trim()
if ($pub -match "'") { Write-Host 'รูปแบบกุญแจไม่ถูกต้อง' -ForegroundColor Red; exit 1 }

try {
  Write-Host "[1/3] ฝากกุญแจไว้ที่ $t (ใส่รหัสผ่าน SSH ถ้าถาม)"
  & ssh $t "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; grep -qxF '$pub' ~/.ssh/authorized_keys || echo '$pub' >> ~/.ssh/authorized_keys; echo OK"
  if ($LASTEXITCODE -ne 0) { throw 'ฝากกุญแจไม่สำเร็จ' }
  Write-Host '[2/3] ส่งสคริปต์อัปเดต'
  & scp -o BatchMode=yes $sh "${t}:~/sp-upgrade.sh"
  if ($LASTEXITCODE -ne 0) { throw 'เข้าด้วยกุญแจไม่ได้ (ตรวจสิทธิ์ ~/.ssh บน Server)' }
  $probe = (Quiet { ssh -o BatchMode=yes $t "docker info >/dev/null 2>&1 && echo DOCKER" }) -join ''
  if ($probe -match 'DOCKER') {
    Write-Host "[3/3] $User อยู่ในกลุ่ม docker แล้ว — ไม่ต้องตั้ง sudo" -ForegroundColor Green
  } else {
    Write-Host "[3/3] อนุญาตคำสั่งอัปเดตแบบไม่ถามรหัส (ใส่รหัส sudo ของ $User ถ้าถาม)"
    $cmd = "set -e; sed -i 's/\r$//' ~/sp-upgrade.sh; sudo install -m 0755 -o root -g root ~/sp-upgrade.sh /usr/local/sbin/sp-upgrade; " +
           "echo '$User ALL=(root) NOPASSWD: /usr/local/sbin/sp-upgrade' | sudo tee /etc/sudoers.d/.smart-parking-upgrade.new >/dev/null; " +
           "sudo chmod 440 /etc/sudoers.d/.smart-parking-upgrade.new; " +
           "if sudo visudo -cf /etc/sudoers.d/.smart-parking-upgrade.new >/dev/null; then sudo mv -f /etc/sudoers.d/.smart-parking-upgrade.new /etc/sudoers.d/smart-parking-upgrade; else sudo rm -f /etc/sudoers.d/.smart-parking-upgrade.new; echo 'sudoers ไม่ผ่านการตรวจ'; exit 1; fi"
    & ssh -t $t $cmd
    if ($LASTEXITCODE -ne 0) { throw 'ตั้งสิทธิ์ sudo ไม่สำเร็จ' }
    $probe = (Quiet { ssh -o BatchMode=yes $t "sudo -n -l /usr/local/sbin/sp-upgrade >/dev/null 2>&1 && echo SUDO" }) -join ''
    if ($probe -notmatch 'SUDO') { throw 'ทดสอบแล้วยังต้องใช้รหัสผ่าน' }
  }
  Write-Host "`nพร้อมอัปเดตอัตโนมัติ — ต่อไปดับเบิลคลิก update-smart-parking-auto.bat ได้เลย" -ForegroundColor Green
} catch { Write-Host "`nไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
