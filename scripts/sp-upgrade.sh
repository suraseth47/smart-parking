#!/usr/bin/env bash
# อัปเดต Smart Parking บน Server จากไฟล์ smart-parking-update.tar.gz ในโฮมโฟลเดอร์ (ส่งมาจากโน้ตบุ๊ก)
#   bash ~/sp-upgrade.sh [SHA256] [ชื่อรุ่น]          (ผู้ใช้อยู่ในกลุ่ม docker หรือจะถามรหัส sudo)
#   sudo -n /usr/local/sbin/sp-upgrade [SHA256] [ชื่อรุ่น]  (โหมดอัตโนมัติ — ตั้งด้วย setup-auto-update-smart-parking.bat)
# ขั้นตอน: ตรวจไฟล์ → สำรองฐานข้อมูล → คัดลอกโค้ดใหม่ทับ (ไม่แตะ .env data/ models/ .git) → build → up -d → ตรวจ
# ไม่ลบไฟล์ที่มีอยู่บน Server (ไฟล์ที่เลิกใช้ในเวอร์ชันใหม่จะค้างอยู่ได้ ไม่มีผลกับการทำงาน)
set -uo pipefail
EXP="${1:-}"
LABEL="${2:-}"
ok()   { echo "  [OK] $*"; }
warn() { echo "  [!!] $*"; }
die()  { echo; echo "  [หยุด] $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

# โฟลเดอร์ของผู้ใช้ที่สั่ง (ถ้ารันผ่าน sudo ใช้โฮมของผู้สั่ง ไม่ใช่ /root)
if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
  HOMEDIR=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
  HOMEDIR="$HOME"
fi
APP_DIR="$HOMEDIR/smart-parking"
[[ -f /etc/smart-parking-upgrade.conf ]] && . /etc/smart-parking-upgrade.conf   # APP_DIR=... (ตั้งโดยผู้ดูแล)
TAR="$HOMEDIR/smart-parking-update.tar.gz"

# สิทธิ์ใช้ docker: root / อยู่ในกลุ่ม docker / ขอ sudo
if [[ $EUID -eq 0 ]] || docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi

step "1/5 ตรวจไฟล์ที่ส่งมา"
[[ -d "$APP_DIR" && -f "$APP_DIR/docker-compose.yml" ]] || die "ไม่พบโปรเจกต์ที่ $APP_DIR (ตั้ง APP_DIR ใน /etc/smart-parking-upgrade.conf)"
[[ -f "$TAR" ]] || die "ไม่พบ $TAR — ส่งไฟล์ด้วยสคริปต์บนโน้ตบุ๊กก่อน"
WORK=$(mktemp -d) || die "สร้างโฟลเดอร์ชั่วคราวไม่ได้"; chmod 700 "$WORK"; trap 'rm -rf "$WORK"' EXIT
cp "$TAR" "$WORK/pkg.tar.gz" || die "คัดลอกไฟล์ไม่ได้"
echo "  โปรเจกต์: $APP_DIR"
echo "  ไฟล์: $(stat -c %s "$TAR") ไบต์"
if [[ -n "$EXP" ]]; then
  GOT=$(sha256sum "$WORK/pkg.tar.gz" | cut -d' ' -f1)
  [[ "${GOT,,}" == "${EXP,,}" ]] || die "SHA256 ไม่ตรงกับไฟล์บนโน้ตบุ๊ก — ส่งไฟล์ใหม่"
  ok "SHA256 ตรงกับไฟล์บนโน้ตบุ๊ก"
fi
mkdir -p "$WORK/pkg" && tar xzf "$WORK/pkg.tar.gz" -C "$WORK/pkg" || die "แตกไฟล์ไม่สำเร็จ"
for f in docker-compose.yml Dockerfile requirements.txt worker/main.py web/main.py; do
  [[ -f "$WORK/pkg/$f" ]] || die "ไฟล์ไม่ครบ (ไม่มี $f) — ไม่ใช่ชุด Smart Parking"
done
# กันพลาด: ห้ามมีไฟล์ที่ต้องเก็บไว้บน Server ติดมาในชุดอัปเดต
rm -rf "$WORK/pkg/.env" "$WORK/pkg/data" "$WORK/pkg/.git" "$WORK/pkg/.venv"
rm -f "$WORK/pkg/models/"*.onnx "$WORK/pkg/Caddyfile.d/"*.caddy 2>/dev/null
echo "  รุ่นที่ติดตั้งอยู่: $(head -1 "$APP_DIR/.deploy-version" 2>/dev/null || echo ไม่ทราบ) → รุ่นใหม่: ${LABEL:-ไม่ทราบ}"

if [[ "$DOCKER" == "sudo docker" ]]; then
  step "ขอสิทธิ์ sudo (ใส่รหัสผ่านของ $(whoami) — ตอนพิมพ์จะไม่เห็นตัวอักษร)"
  sudo -v || die "sudo ไม่ผ่าน"
fi

step "2/5 สำรองฐานข้อมูลก่อนอัปเดต"
cd "$APP_DIR" || die "เข้าโฟลเดอร์ $APP_DIR ไม่ได้"
BK=$($DOCKER compose exec -T worker python -c "
from datetime import datetime
from core.backup import run_backup
from core.config import get_settings
s = get_settings()
r = run_backup(s.db_path, s.data_dir / 'backups', datetime.now(), 'before-update')
print(('OK ' + r['file']) if r.get('ok') else ('FAIL ' + str(r.get('message'))))
" 2>/dev/null | tail -1)
if [[ "$BK" == OK* ]]; then ok "สำรองแล้ว: data/backups/${BK#OK }"
elif [[ -f data/app.db ]] && command -v sqlite3 >/dev/null; then
  mkdir -p data/backups && sqlite3 data/app.db ".backup 'data/backups/app_before_update_$(date +%Y%m%d_%H%M%S).db'" && ok "สำรองด้วย sqlite3 แล้ว" || warn "สำรองไม่สำเร็จ"
else
  warn "สำรองผ่าน worker ไม่ได้ (worker ไม่ทำงาน?) และไม่มี sqlite3 บนเครื่อง"
  if [[ -t 0 ]]; then
    read -rp "  ดำเนินการต่อโดยไม่มีสำรองล่าสุด? (พิมพ์ y แล้ว Enter = ต่อ / Enter = หยุด): " a
    [[ "$a" == "y" ]] || die "หยุดตามที่เลือก"
  else
    die "หยุด (โหมดอัตโนมัติจะไม่อัปเดตถ้าสำรองไม่ได้) — ลองรันแบบถามรหัส หรือติดตั้ง sqlite3"
  fi
fi

step "3/5 คัดลอกโค้ดใหม่ (ไม่แตะ .env data/ models/ .git)"
OWNER=$(stat -c '%u:%g' "$APP_DIR")
[[ $EUID -eq 0 ]] && chown -R "$OWNER" "$WORK/pkg"   # ให้ไฟล์เป็นของเจ้าของโปรเจกต์ ไม่ใช่ root
cp -a "$WORK/pkg/." "$APP_DIR/" || die "คัดลอกไม่สำเร็จ (สิทธิ์ไฟล์ใน $APP_DIR?)"
echo "${LABEL:-$(date '+%d/%m/%Y %H:%M')}" > "$APP_DIR/.deploy-version"
[[ $EUID -eq 0 ]] && chown "$OWNER" "$APP_DIR/.deploy-version"
# สคริปต์อัปเดตรุ่นใหม่สำหรับโหมดอัตโนมัติ (เขียนไฟล์ใหม่แล้ว mv กันทับไฟล์ที่กำลังรัน)
if [[ $EUID -eq 0 && -f "$APP_DIR/scripts/sp-upgrade.sh" ]]; then
  tr -d '\r' < "$APP_DIR/scripts/sp-upgrade.sh" > /usr/local/sbin/.sp-upgrade.new && chmod 0755 /usr/local/sbin/.sp-upgrade.new \
    && mv -f /usr/local/sbin/.sp-upgrade.new /usr/local/sbin/sp-upgrade
fi
ok "คัดลอกแล้ว"

step "4/5 build และเริ่มระบบใหม่ (ประมาณ 1–5 นาที · migration ฐานข้อมูลรันเองตอน start)"
$DOCKER compose build || die "build ไม่สำเร็จ — ระบบเดิมยังทำงานอยู่ ส่งข้อความ error ด้านบนให้ผู้ดูแล"
$DOCKER compose up -d || die "เริ่มระบบไม่สำเร็จ — ดู: docker compose logs --tail 50"

step "5/5 ตรวจหลังอัปเดต"
FAIL=0
for i in $(seq 1 30); do
  code=$($DOCKER compose exec -T web python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/', timeout=5).status)" 2>/dev/null | tail -1)
  [[ "$code" == 200 ]] && break
  sleep 3
done
[[ "$code" == 200 ]] && ok "หน้าเว็บตอบปกติ" || { warn "หน้าเว็บยังไม่ตอบ — ดู: docker compose logs --tail 50 web"; FAIL=1; }
for s in web worker caddy; do
  if [[ -n "$($DOCKER compose ps --status running -q "$s" 2>/dev/null)" ]]; then ok "บริการ $s ทำงาน"
  else warn "บริการ $s ไม่ทำงาน — ดู: docker compose logs --tail 50 $s"; FAIL=1; fi
done
$DOCKER compose logs --tail 200 worker 2>/dev/null | grep -m1 "ใช้โมเดล" | sed 's/^/  /'
echo "  รุ่นที่ติดตั้งตอนนี้: $(head -1 "$APP_DIR/.deploy-version")"
[[ $FAIL == 1 ]] && die "อัปเดตแล้วแต่บางบริการไม่ทำงาน — ฐานข้อมูลสำรองไว้ใน data/backups แล้ว"
echo; echo "เสร็จแล้ว — เปิดหลังบ้านแล้วกด Ctrl+F5"
