"""ค่าตั้งระบบที่แก้ได้จากหน้า "ตั้งค่าระบบ → ระบบและการแสดงผล" (เก็บในตาราง settings)

- display: ชื่อหน่วยงาน/ข้อความหัวจอ และสวิตช์แสดง/ซ่อนส่วนต่าง ๆ ของหลังบ้านและหน้าสาธารณะ
- health:  การตรวจกล้องถูกขยับ (worker อ่านทุกรอบ)

ค่าที่ยังไม่เคยบันทึกใช้ค่าเริ่มต้นจาก .env (SYSTEM_TITLE, ORG_NAME) แล้วค่าคงที่ในไฟล์นี้
"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Setting

DISPLAY_SETTING_KEY = "display"
HEALTH_SETTING_KEY = "health"

# สวิตช์หน้าสาธารณะ: key -> ค่าเริ่มต้น
PUBLIC_TOGGLES = {
    "lang_switch": True,     # ปุ่มสลับภาษา ไทย/EN
    "directions": True,      # ปุ่มนำทาง Google Maps
    "nearby_sort": True,     # ปุ่มเรียงสถานที่ใกล้ฉัน
    "free_list": True,       # รายการรหัสช่องที่ว่าง
    "slot_map": True,        # ปุ่มดูผังช่องจอด
    "peak_chart": True,      # กราฟช่วงเวลาที่คนจอดมาก
}

HEALTH_DEFAULTS = {
    "moved_check_enabled": True,
    "moved_check_interval_min": 10,
    "moved_threshold_px": 50,
}
HEALTH_LIMITS = {"moved_check_interval_min": (1, 120), "moved_threshold_px": (10, 300)}


def display_defaults() -> dict:
    settings = get_settings()
    return {
        "org_name": settings.org_name,
        "system_title": f"{settings.system_title} {settings.org_name}".strip(),  # ข้อความหัวจอเต็มบรรทัด
        "show_system_title": True,
        "show_server_address": True,
        "show_sidebar_footer": True,
        "public": dict(PUBLIC_TOGGLES),
    }


def _merge(defaults: dict, saved: dict | None) -> dict:
    result = dict(defaults)
    for key, value in (saved or {}).items():
        if key not in defaults:
            continue
        if isinstance(defaults[key], dict) and isinstance(value, dict):
            result[key] = {k: bool(value.get(k, v)) for k, v in defaults[key].items()}
        elif isinstance(defaults[key], bool):
            result[key] = bool(value)
        else:
            result[key] = value
    return result


def load_display(db: Session) -> dict:
    row = db.get(Setting, DISPLAY_SETTING_KEY)
    return _merge(display_defaults(), row.value if row else None)


def load_health(db: Session) -> dict:
    row = db.get(Setting, HEALTH_SETTING_KEY)
    merged = _merge(HEALTH_DEFAULTS, row.value if row else None)
    for key, (low, high) in HEALTH_LIMITS.items():
        try:
            merged[key] = min(high, max(low, int(merged[key])))
        except (TypeError, ValueError):
            merged[key] = HEALTH_DEFAULTS[key]
    return merged


def save_setting(db: Session, key: str, value: dict) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    if key == DISPLAY_SETTING_KEY:
        invalidate_display_cache()


# ---------- cache สำหรับ template (ทุกหน้า render อ่านค่านี้ ไม่ต้อง query ทุกครั้ง) ----------
_CACHE_SECONDS = 30
_cache: dict = {"at": 0.0, "value": None}


def invalidate_display_cache() -> None:
    _cache["at"] = 0.0
    _cache["value"] = None


def cached_display() -> dict:
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < _CACHE_SECONDS:
        return _cache["value"]
    try:
        from core.db import SessionLocal

        with SessionLocal() as db:
            value = load_display(db)
    except Exception:  # noqa: BLE001 — DB ยังไม่พร้อม (เช่น ก่อน migrate) ใช้ค่าเริ่มต้นไปก่อน
        value = display_defaults()
    _cache["at"] = now
    _cache["value"] = value
    return value
