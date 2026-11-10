# ลงไฟล์อัปเดต (.zip ที่ได้จาก Claude) ครบในคลิกเดียว: แตกไฟล์ลงโปรเจกต์ → อัปเดต Server → git commit → git push
# วิธีใช้:
#   ดับเบิลคลิก apply-update-smart-parking.bat         = หา zip ล่าสุดในโฟลเดอร์ Downloads / D:\Naslink ให้เอง แล้วถามยืนยัน
#   ลากไฟล์ .zip มาวางบน apply-update-smart-parking.bat = ใช้ไฟล์นั้น
# ข้อความ commit: อ่านจากไฟล์ .update-message.txt ใน zip (ถ้ามี) ไม่มีก็ถามให้พิมพ์
# zip ที่ลงสำเร็จแล้ว ถูกย้ายไปเก็บที่ D:\Naslink\Script\applied เพื่อไม่ให้ลงซ้ำ
param(
  [string]$Zip = '',
  [string]$Project = '',
  [switch]$Yes,
  [switch]$NoPush
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Say([string]$t, [string]$c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Fail([string]$t) { Say "`n[X] $t" Red; exit 1 }
function Git-Quiet { $o = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { & git @args 2>&1 } finally { $ErrorActionPreference = $o } }

# โฟลเดอร์ที่อนุญาตให้อยู่ใน zip อัปเดต (กันแตกไฟล์แปลก ๆ ทับโปรเจกต์)
$AllowedTop = @('web', 'core', 'worker', 'tests', 'migrations', 'scripts', 'docs', 'deploy', 'models',
  'CHANGELOG.md', 'README.md', 'SPEC.md', 'pyproject.toml', 'requirements.txt', 'docker-compose.yml', 'Dockerfile',
  'Caddyfile', 'alembic.ini', '.env.example', '.gitignore', '.update-message.txt')
$Blocked = '^(\.env$|data/|\.git/|\.venv/|models/.*\.onnx$)'

# ---------- โปรเจกต์ ----------
if (-not $Project) {
  $up = Split-Path $PSScriptRoot -Parent
  $Project = if (Test-Path (Join-Path $up 'docker-compose.yml')) { $up } else { 'D:\Naslink\Smart-Parking' }
}
if (-not (Test-Path (Join-Path $Project 'docker-compose.yml'))) { Fail "ไม่พบโปรเจกต์ Smart Parking ที่ $Project" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'ไม่พบคำสั่ง git บนโน้ตบุ๊ก' }
$naslink = Split-Path $Project -Parent

# ---------- ตรวจ zip: ต้องเป็นไฟล์โค้ดของโปรเจกต์นี้เท่านั้น ----------
function Get-ZipEntries([string]$path) {
  try {
    $z = [IO.Compression.ZipFile]::OpenRead($path)
    try { return @($z.Entries | Where-Object { $_.Name } | ForEach-Object { $_.FullName.Replace('\', '/') }) } finally { $z.Dispose() }
  } catch { return $null }
}
function Test-UpdateZip([string]$path) {
  $e = Get-ZipEntries $path
  if (-not $e -or $e.Count -eq 0) { return $false }
  foreach ($n in $e) {
    $top = ($n -split '/')[0]
    if ($AllowedTop -notcontains $top -or $n -match $Blocked -or $n -match '\.\.') { return $false }
  }
  return $true
}

# ---------- หา zip ----------
if (-not $Zip) {
  $dirs = @()
  try { $dirs += (New-Object -ComObject Shell.Application).Namespace('shell:Downloads').Self.Path } catch { }
  $dirs += @((Join-Path $env:USERPROFILE 'Downloads'), (Join-Path $env:USERPROFILE 'Desktop'), $naslink, (Join-Path $naslink 'Script'))
  $since = (Get-Date).AddDays(-14)
  $cand = $dirs | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique |
    ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter '*.zip' -File -ErrorAction SilentlyContinue } |
    Where-Object { $_.LastWriteTime -gt $since -and $_.Length -lt 50MB } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 15 |
    Where-Object { Test-UpdateZip $_.FullName }
  if (-not $cand) { Fail "ไม่พบไฟล์ zip อัปเดตในโฟลเดอร์ Downloads / $naslink (ดาวน์โหลดจากแชตก่อน หรือลากไฟล์ zip มาวางบน .bat)" }
  $Zip = @($cand)[0].FullName
  if (@($cand).Count -gt 1) {
    Say 'พบไฟล์อัปเดตหลายไฟล์ ใช้ไฟล์ล่าสุด (ไฟล์อื่น ลากมาวางบน .bat ได้):' DarkGray
    @($cand) | ForEach-Object { Say ("   {0:dd/MM HH:mm}  {1}" -f $_.LastWriteTime, $_.FullName) DarkGray }
  }
}
if (-not (Test-Path -LiteralPath $Zip)) { Fail "ไม่พบไฟล์ $Zip" }
if (-not (Test-UpdateZip $Zip)) { Fail "ไฟล์นี้ไม่ใช่ zip อัปเดต Smart Parking (มีไฟล์นอกโฟลเดอร์โปรเจกต์ หรือไฟล์ต้องห้าม): $Zip" }
$entries = Get-ZipEntries $Zip | Where-Object { $_ -ne '.update-message.txt' }

# ---------- สรุปก่อนเริ่ม ----------
Push-Location $Project
try {
  $dirty = @(Git-Quiet status --porcelain | Where-Object { $_ })
  $branch = (Git-Quiet rev-parse --abbrev-ref HEAD | Select-Object -First 1)
} finally { Pop-Location }
Say "`n=== ลงไฟล์อัปเดต Smart Parking ===" Cyan
Say "ไฟล์อัปเดต : $Zip"
Say "โปรเจกต์   : $Project  (branch $branch)"
Say "จำนวนไฟล์  : $($entries.Count) ไฟล์"
$entries | Select-Object -First 25 | ForEach-Object { Say "   - $_" DarkGray }
if ($entries.Count -gt 25) { Say "   ... และอีก $($entries.Count - 25) ไฟล์" DarkGray }
if ($dirty.Count) {
  Say "`n[!] โปรเจกต์มีงานที่ยังไม่ commit $($dirty.Count) ไฟล์ — จะถูกรวมไปใน commit นี้ด้วย:" Yellow
  $dirty | Select-Object -First 10 | ForEach-Object { Say "   $_" Yellow }
}
if (-not $Yes) { $go = Read-Host "`nเริ่มเลย? แตกไฟล์ → อัปเดต Server → commit → push (y = ใช่)"; if ($go -ne 'y') { Say 'ยกเลิก'; exit 0 } }

# ---------- 1) แตกไฟล์ลงโปรเจกต์ ----------
Say "`n[1/4] แตกไฟล์ลงโปรเจกต์" Cyan
$tmp = Join-Path $env:TEMP 'smart-parking-apply'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -LiteralPath $Zip -DestinationPath $tmp -Force
$msgFile = Join-Path $tmp '.update-message.txt'
$message = if (Test-Path $msgFile) { (Get-Content $msgFile -Raw -Encoding UTF8).Trim() } else { '' }
foreach ($rel in $entries) {
  $src = Join-Path $tmp ($rel -replace '/', '\')
  $dst = Join-Path $Project ($rel -replace '/', '\')
  New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
  Copy-Item -LiteralPath $src -Destination $dst -Force
}
Remove-Item $tmp -Recurse -Force
Say "  [OK] คัดลอก $($entries.Count) ไฟล์แล้ว" Green

# ---------- 2) อัปเดต Server (สคริปต์เดิม โหมดไม่ถาม) ----------
Say "`n[2/4] อัปเดต Server" Cyan
$updater = Join-Path $Project 'scripts\update-smart-parking.ps1'
& powershell -NoProfile -ExecutionPolicy Bypass -File $updater -Yes -Project $Project
if ($LASTEXITCODE -ne 0) {
  Fail "อัปเดต Server ไม่สำเร็จ — ไฟล์อยู่ในโปรเจกต์แล้ว ยังไม่ได้ commit`n    แก้ปัญหาตามข้อความด้านบน แล้วดับเบิลคลิก apply-update-smart-parking.bat ใหม่ได้เลย (zip ยังอยู่ที่เดิม)"
}

# ---------- 3) git commit ----------
Say "`n[3/4] git commit" Cyan
if (-not $message) {
  $message = (Read-Host 'ข้อความ commit (Enter = ใช้ข้อความอัตโนมัติ)').Trim()
  if (-not $message) { $message = 'อัปเดต Smart Parking ' + (Get-Date).ToString('dd/MM/') + ((Get-Date).Year + 543) + ' (' + [IO.Path]::GetFileNameWithoutExtension($Zip) + ')' }
}
Push-Location $Project
try {
  Git-Quiet add -A | Out-Null
  $staged = @(Git-Quiet diff --cached --name-only | Where-Object { $_ })
  if (-not $staged.Count) {
    Say '  ไม่มีไฟล์ที่เปลี่ยน (ไฟล์ใน zip เหมือนของเดิมทุกไฟล์) — ข้าม commit' Yellow
  } else {
    # ส่งข้อความผ่านไฟล์ UTF-8 (PowerShell 5.1 ส่งภาษาไทยเป็นอาร์กิวเมนต์ให้ git แล้วเพี้ยน)
    $mf = Join-Path $env:TEMP 'smart-parking-commit-msg.txt'
    [IO.File]::WriteAllText($mf, $message + "`n", (New-Object Text.UTF8Encoding $false))
    $out = Git-Quiet commit -F $mf
    if ($LASTEXITCODE -ne 0) { $out | ForEach-Object { Say "  $_" Red }; Fail 'git commit ไม่สำเร็จ (ดูข้อความด้านบน)' }
    Say "  [OK] $($staged.Count) ไฟล์ · $message" Green
  }

  # ---------- 4) git push ----------
  Say "`n[4/4] git push" Cyan
  if ($NoPush) { Say '  ข้าม (สั่ง -NoPush)' Yellow }
  else {
    $out = Git-Quiet push
    if ($LASTEXITCODE -ne 0) {
      $out | ForEach-Object { Say "  $_" Yellow }
      Say '  [!] push ไม่สำเร็จ — commit อยู่ในโน้ตบุ๊กแล้ว (Server อัปเดตแล้ว) ลอง git pull แล้ว git push ใหม่ภายหลัง' Yellow
    } else { Say '  [OK] ส่งขึ้น GitHub แล้ว' Green }
  }
} finally { Pop-Location }

# ---------- เก็บ zip ที่ลงแล้ว ----------
$applied = Join-Path $naslink 'Script\applied'
try {
  New-Item -ItemType Directory -Force $applied | Out-Null
  $name = (Get-Date).ToString('yyyyMMdd-HHmm') + '_' + [IO.Path]::GetFileName($Zip)
  Move-Item -LiteralPath $Zip -Destination (Join-Path $applied $name) -Force
  Say "`nย้าย zip ไปเก็บที่ $applied\$name (กันลงซ้ำ)" DarkGray
} catch { Say "`n(ย้าย zip ไม่ได้: $($_.Exception.Message))" DarkGray }

Say "`nเสร็จแล้ว — เปิดหลังบ้านแล้วกด Ctrl+F5" Green
