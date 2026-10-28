#!/bin/sh
# สำรองฐานข้อมูล SQLite อัตโนมัติ เก็บ 14 ชุดล่าสุด (NFR-7)
#
# หมายเหตุ: ตั้งแต่ 2026-10 worker สำรองให้เองทุกวันแล้ว (core/backup.py) สคริปต์นี้ใช้เสริมได้แต่ไม่จำเป็น
#
# รันบนเครื่อง host โดยตรง (ไม่ผ่าน container) เพราะ data/ เป็น bind mount
# เข้าถึงจาก host ได้ตรงๆ อยู่แล้ว ต้องติดตั้ง sqlite3 บน host ก่อน:
#   sudo apt install sqlite3
#
# ใช้คำสั่ง `sqlite3 .backup` แทนการ cp ไฟล์ตรงๆ เพราะ DB เปิด WAL mode
# (worker/web เขียนอยู่ตลอด) การ cp ไฟล์ดิบระหว่างมีคนเขียนอาจได้ไฟล์ไม่สมบูรณ์
#
# ตั้ง cron ให้รันวันละครั้ง เช่น ทุกตี 3 (แก้ path ให้ตรงกับเครื่องจริง):
#   0 3 * * * /path/to/smart-parking/scripts/backup.sh >> /var/log/smart-parking-backup.log 2>&1

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/app.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
RETENTION_COUNT=14

if [ ! -f "$DB_PATH" ]; then
    echo "ไม่พบไฟล์ฐานข้อมูล: $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/app_${TIMESTAMP}.db"

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
echo "สำรองฐานข้อมูลสำเร็จ: $BACKUP_FILE"

# เก็บไว้แค่ $RETENTION_COUNT ชุดล่าสุด ลบที่เก่ากว่านั้นทิ้ง (NFR-7)
ls -1t "$BACKUP_DIR"/app_*.db 2>/dev/null | tail -n "+$((RETENTION_COUNT + 1))" | while read -r old_file; do
    rm -f "$old_file"
    echo "ลบไฟล์สำรองเก่า: $old_file"
done
