# อัปเดต Smart Parking ลง Server (192.168.200.196) จากโฟลเดอร์โปรเจกต์บนโน้ตบุ๊ก
# วิธีใช้:
#   ดับเบิลคลิก update-smart-parking.bat        = ถามยืนยันก่อน
#   ดับเบิลคลิก update-smart-parking-auto.bat   = ไม่ถามยืนยัน
# ขั้นตอน: รวบรวมไฟล์โค้ด (ไม่รวม .env data/ models/*.onnx .venv และไฟล์ใน .gitignore) → ส่งไป Server
#          → Server สำรองฐานข้อมูล → คัดลอกโค้ดทับ → docker compose build / up -d → ตรวจ
# โหมดอัตโนมัติ (ไม่ต้องใส่รหัสผ่าน): ตั้งครั้งเดียวด้วย setup-auto-update-smart-parking.bat
param(
  [string]$Server = '192.168.200.196',
  [string]$User = '',
  [string]$Project = '',
  [switch]$Yes
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
# เรียก ssh แบบเงียบ (PowerShell 5.1 + ErrorAction Stop จะหยุดทันทีถ้าคำสั่งภายนอกเขียน stderr)
function Quiet([scriptblock]$b) { $o = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { & $b 2>$null } catch { $null } finally { $ErrorActionPreference = $o } }

# โฟลเดอร์โปรเจกต์: โฟลเดอร์แม่ของ scripts\ (ถ้ารันจากในโปรเจกต์) หรือ D:\Naslink\Smart-Parking
if (-not $Project) {
  $up = Split-Path $PSScriptRoot -Parent
  $Project = if (Test-Path (Join-Path $up 'docker-compose.yml')) { $up } else { 'D:\Naslink\Smart-Parking' }
}
if (-not (Test-Path (Join-Path $Project 'docker-compose.yml'))) { Write-Host "ไม่พบโปรเจกต์ Smart Parking ที่ $Project" -ForegroundColor Red; exit 1 }
$remoteSh = Join-Path $Project 'scripts\sp-upgrade.sh'
foreach ($c in 'ssh', 'scp', 'git') { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Write-Host "ไม่พบคำสั่ง $c บนโน้ตบุ๊ก" -ForegroundColor Red; exit 1 } }

# ชื่อผู้ใช้ SSH (ใช้ไฟล์เดียวกับ open-server-admin.bat)
$userFile = Join-Path $env:USERPROFILE '.smart-parking-ssh-user'
if (-not $User -and (Test-Path $userFile)) { $User = (Get-Content $userFile -Raw).Trim() }
if (-not $User) { $User = (Read-Host 'ชื่อผู้ใช้ SSH ของคุณบน Server').Trim(); if (-not $User) { exit 1 }; Set-Content -Path $userFile -Value $User -Encoding ASCII }
$t = "$User@$Server"

# 1) รวบรวมไฟล์: ไฟล์ที่ git รู้จัก + ไฟล์ใหม่ที่ไม่ถูก .gitignore (รวมงานที่ยังไม่ commit)
Push-Location $Project
try {
  $files = & git -c core.quotepath=off ls-files -co --exclude-standard
  if ($LASTEXITCODE -ne 0) { throw 'อ่านรายชื่อไฟล์จาก git ไม่ได้' }
  $files = $files | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) -and $_ -notmatch '^(\.env$|data/|\.venv/|models/.*\.onnx$)' }
  $hash = (& git rev-parse --short HEAD).Trim()
  $dirty = if (& git status --porcelain) { '+local' } else { '' }   # +local = มีงานที่ยังไม่ commit
} finally { Pop-Location }
$now = Get-Date
$label = "{0}/{1} {2} {3}{4}" -f $now.ToString('dd/MM'), ($now.Year + 543), $now.ToString('HH:mm'), $hash, $dirty   # ภาษาอังกฤษล้วน ส่งผ่าน ssh ได้ไม่เพี้ยน
$tmp = Join-Path $env:TEMP 'smart-parking-update'
New-Item -ItemType Directory -Force $tmp | Out-Null
# คัดลอกไฟล์ไปโฟลเดอร์ชั่วคราวก่อน แล้วค่อย tar ทั้งโฟลเดอร์
# (tar -T ของ Windows อ่านชื่อไฟล์ภาษาไทยในรายการไม่ได้ จึงไม่ใช้รายการไฟล์ตรงๆ)
$stage = Join-Path $tmp 'pkg'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
foreach ($f in $files) {
  $dest = Join-Path $stage $f
  New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
  Copy-Item -LiteralPath (Join-Path $Project $f) -Destination $dest -Force
}
$pkg = Join-Path $tmp 'smart-parking-update.tar.gz'
if (Test-Path $pkg) { Remove-Item $pkg -Force }
# ใช้ tar ของ Windows (C:\Windows\System32) — tar ของ Git for Windows อ่าน D:\ เป็นชื่อเครื่องปลายทาง
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $tarExe)) { Write-Host 'ไม่พบ tar.exe ของ Windows (ต้องเป็น Windows 10 1803 ขึ้นไป)' -ForegroundColor Red; exit 1 }
& $tarExe -czf $pkg -C $stage .
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pkg)) { Write-Host 'สร้างไฟล์ชุดอัปเดตไม่สำเร็จ' -ForegroundColor Red; exit 1 }
$sha = (Get-FileHash $pkg -Algorithm SHA256).Hash.ToLower()

Write-Host "โปรเจกต์   : $Project"
Write-Host "รุ่น        : $label"
Write-Host "ไฟล์       : $($files.Count) ไฟล์ · $((Get-Item $pkg).Length) ไบต์"
Write-Host "Server     : $t"
if (-not $Yes) { $go = Read-Host 'เริ่มอัปเดต? (y = ใช่)'; if ($go -ne 'y') { Write-Host 'ยกเลิก'; exit 0 } }

try {
  # โหมดอัตโนมัติ: กุญแจ ssh + (อยู่ในกลุ่ม docker หรือ sudo เฉพาะคำสั่งอัปเดต)
  $probe = (Quiet { ssh -o BatchMode=yes -o ConnectTimeout=8 $t "docker info >/dev/null 2>&1 && echo DOCKER; sudo -n -l /usr/local/sbin/sp-upgrade >/dev/null 2>&1 && echo SUDO" }) -join ' '
  if ($probe -match 'DOCKER|SUDO') {
    Write-Host "`n[โหมดอัตโนมัติ] ไม่ต้องใส่รหัสผ่าน" -ForegroundColor Green
    Write-Host '[1/2] ส่งไฟล์'
    & scp -o BatchMode=yes $pkg $remoteSh "${t}:~/"
    if ($LASTEXITCODE -ne 0) { throw 'scp ไม่สำเร็จ' }
    Write-Host '[2/2] อัปเดตบน Server'
    $cmd = if ($probe -match 'DOCKER') { "sed -i 's/\r$//' ~/sp-upgrade.sh; bash ~/sp-upgrade.sh $sha '$label'" } else { "sudo -n /usr/local/sbin/sp-upgrade $sha '$label'" }
    & ssh -o BatchMode=yes $t $cmd
  } else {
    Write-Host "`n[ยังไม่ได้ตั้งโหมดอัตโนมัติ — จะถามรหัสผ่าน]" -ForegroundColor Yellow
    Write-Host "[1/2] ส่งไฟล์ (ใส่รหัสผ่าน SSH ของ $User)"
    & scp $pkg $remoteSh "${t}:~/"
    if ($LASTEXITCODE -ne 0) { throw 'scp ไม่สำเร็จ (ตรวจ IP / ชื่อผู้ใช้ / รหัสผ่าน / VPN)' }
    Write-Host '[2/2] อัปเดตบน Server (ใส่รหัสผ่าน SSH แล้วรหัส sudo ถ้าถาม)'
    & ssh -t $t "sed -i 's/\r$//' ~/sp-upgrade.sh; bash ~/sp-upgrade.sh $sha '$label'"
  }
  if ($LASTEXITCODE -ne 0) { throw 'อัปเดตไม่สำเร็จ (ดูข้อความด้านบน)' }
  Write-Host "`nสำเร็จ · $label" -ForegroundColor Green
  Write-Host 'เปิดหลังบ้านแล้วกด Ctrl+F5'
} catch {
  Write-Host "`nไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
