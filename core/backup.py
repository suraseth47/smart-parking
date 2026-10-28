"""สำรองฐานข้อมูล SQLite อัตโนมัติ (NFR-7, TOR 5.1) — ทำงานใน worker ไม่ต้องตั้ง cron บนเครื่อง host

- ใช้ sqlite3 backup API (เทียบเท่าคำสั่ง `.backup`) ได้ไฟล์สมบูรณ์แม้มีคนเขียนฐานข้อมูลอยู่ (WAL)
- ตรวจไฟล์สำรองด้วย PRAGMA integrity_check ทุกครั้ง
- เก็บ BACKUP_KEEP ชุดล่าสุด (ค่าเริ่มต้น 14 ตาม SPEC) ลบชุดที่เก่ากว่า
- ถ้าตั้ง BACKUP_COPY_DIR (เช่น โฟลเดอร์ NAS ที่ mount เข้ามา) จะคัดลอกไปเก็บนอกเครื่องด้วย
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

FILE_PREFIX = "app_"
FILE_SUFFIX = ".db"
STATUS_FILE = "status.json"
DEFAULT_KEEP = 14
DEFAULT_HOUR = 3  # ตี 3 เวลาท้องถิ่น


@dataclass
class BackupFile:
    name: str
    size: int
    created_at: datetime  # เวลาท้องถิ่น (จากชื่อไฟล์)


def backup_keep() -> int:
    try:
        return max(7, int(os.environ.get("BACKUP_KEEP", DEFAULT_KEEP)))  # TOR: ไม่น้อยกว่า 7 วัน
    except ValueError:
        return DEFAULT_KEEP


def backup_hour() -> int:
    try:
        return min(23, max(0, int(os.environ.get("BACKUP_HOUR", DEFAULT_HOUR))))
    except ValueError:
        return DEFAULT_HOUR


def copy_dir() -> Path | None:
    value = os.environ.get("BACKUP_COPY_DIR", "").strip()
    return Path(value) if value else None


def backup_name(local_now: datetime) -> str:
    return f"{FILE_PREFIX}{local_now:%Y%m%d_%H%M%S}{FILE_SUFFIX}"


def parse_backup_time(name: str) -> datetime | None:
    if not (name.startswith(FILE_PREFIX) and name.endswith(FILE_SUFFIX)):
        return None
    try:
        return datetime.strptime(name[len(FILE_PREFIX):-len(FILE_SUFFIX)], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def list_backups(backup_dir: Path) -> list[BackupFile]:
    """ไฟล์สำรองเรียงจากใหม่ไปเก่า"""
    if not backup_dir.exists():
        return []
    files = []
    for path in backup_dir.iterdir():
        created = parse_backup_time(path.name)
        if created is not None and path.is_file():
            files.append(BackupFile(name=path.name, size=path.stat().st_size, created_at=created))
    return sorted(files, key=lambda f: f.created_at, reverse=True)


def files_to_prune(files: list[BackupFile], keep: int) -> list[BackupFile]:
    """pure function: ไฟล์ที่เกินจำนวนที่เก็บ (files เรียงใหม่ -> เก่า)"""
    return files[keep:]


def is_backup_due(files: list[BackupFile], local_now: datetime, hour: int) -> bool:
    """pure function: ถึงเวลาสำรองของวันนี้แล้ว และวันนี้ยังไม่มีไฟล์สำรองที่ทำหลังเวลานั้น"""
    if local_now.hour < hour:
        return False
    today_slot = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return not any(f.created_at >= today_slot for f in files)


def run_backup(db_path: Path, backup_dir: Path, local_now: datetime, reason: str = "auto") -> dict:
    """สำรอง 1 ครั้ง + ตรวจความสมบูรณ์ + ลบชุดเก่า + คัดลอกออกนอกเครื่อง (ถ้าตั้งไว้) แล้วบันทึกสถานะ"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / backup_name(local_now)
    status: dict = {"time": local_now.isoformat(timespec="seconds"), "reason": reason, "file": target.name}
    try:
        if not db_path.is_file():
            raise FileNotFoundError(f"ไม่พบไฟล์ฐานข้อมูล {db_path}")  # กัน sqlite สร้างไฟล์ว่างแล้วสำรองไฟล์ว่าง
        source = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)  # อ่านอย่างเดียว ใช้ได้ทั้ง Linux/Windows
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        check = sqlite3.connect(str(target))
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if result != "ok":
            raise RuntimeError(f"ตรวจไฟล์สำรองไม่ผ่าน: {result}")
        status.update(ok=True, size=target.stat().st_size, message="สำรองและตรวจความสมบูรณ์แล้ว")

        removed = []
        for old in files_to_prune(list_backups(backup_dir), backup_keep()):
            (backup_dir / old.name).unlink(missing_ok=True)
            removed.append(old.name)
        status["removed"] = removed

        status["copy"] = _copy_offsite(target)
    except Exception as exc:  # noqa: BLE001 — บันทึกสาเหตุไว้ให้หน้าเว็บแสดง ไม่ให้ worker ล้ม
        target.unlink(missing_ok=True)
        status.update(ok=False, message=f"สำรองไม่สำเร็จ: {exc}")
    _write_status(backup_dir, status)
    return status


def _copy_offsite(target: Path) -> dict | None:
    dest_dir = copy_dir()
    if dest_dir is None:
        return None
    try:
        if not dest_dir.is_dir():
            return {"ok": False, "message": f"ไม่พบโฟลเดอร์ปลายทาง {dest_dir} (NAS ยังไม่ได้ mount?)"}
        shutil.copy2(target, dest_dir / target.name)
        for old in files_to_prune(list_backups(dest_dir), backup_keep()):
            (dest_dir / old.name).unlink(missing_ok=True)
        return {"ok": True, "message": f"คัดลอกไปที่ {dest_dir} แล้ว"}
    except OSError as exc:
        return {"ok": False, "message": f"คัดลอกออกนอกเครื่องไม่สำเร็จ: {exc}"}


def _write_status(backup_dir: Path, status: dict) -> None:
    (backup_dir / STATUS_FILE).write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def read_status(backup_dir: Path) -> dict | None:
    path = backup_dir / STATUS_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def days_covered(files: list[BackupFile]) -> int:
    """จำนวนวันที่มีไฟล์สำรอง (ใช้แสดงว่าครบ 7 วันตาม TOR หรือยัง)"""
    return len({f.created_at.date() for f in files})

