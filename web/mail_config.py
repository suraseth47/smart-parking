"""ค่าการส่งอีเมลและลิงก์คำเชิญ ที่ Admin ตั้งจากหน้าเว็บ (ตั้งค่าระบบ → อีเมลและลิงก์คำเชิญ)

เก็บในตาราง settings:
- "mail":   {host, port, user, password_enc, from_address, security}  — รหัสผ่านเข้ารหัสด้วย FERNET_KEY
- "invite": {base_url, default_expiry_days}

ถ้ายังไม่ได้ตั้งจากหน้าเว็บ จะใช้ค่า SMTP_* / PUBLIC_IP ใน .env แทน (ถ้ามี)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import SmtpSettings, get_settings
from core.models import Setting
from core.security import decrypt_camera_password

MAIL_SETTING_KEY = "mail"
INVITE_SETTING_KEY = "invite"
DEFAULT_EXPIRY_DAYS = 3
MAX_EXPIRY_DAYS = 30


def _setting_value(db: Session, key: str) -> dict:
    setting = db.get(Setting, key)
    return setting.value if setting and isinstance(setting.value, dict) else {}


def smtp_source(db: Session) -> str:
    """ค่าที่ใช้อยู่มาจากไหน: "web" (ตั้งจากหน้าเว็บ) | "env" (.env) | "none" (ยังไม่ได้ตั้ง)"""
    if _setting_value(db, MAIL_SETTING_KEY).get("host"):
        return "web"
    return "env" if get_settings().smtp.configured else "none"


def get_smtp(db: Session) -> SmtpSettings:
    """ค่าที่ใช้ส่งจริง: จากหน้าเว็บก่อน ไม่มีค่อยใช้ .env"""
    value = _setting_value(db, MAIL_SETTING_KEY)
    if not value.get("host"):
        return get_settings().smtp
    password = ""
    if value.get("password_enc"):
        try:
            password = decrypt_camera_password(value["password_enc"])
        except Exception:  # noqa: BLE001 — FERNET_KEY เปลี่ยน: ถอดไม่ได้ ให้ส่งไม่ผ่านพร้อมข้อความ login ผิดแทนการล่ม
            password = ""
    user = value.get("user") or ""
    return SmtpSettings(
        host=value["host"],
        port=int(value.get("port") or 587),
        user=user,
        password=password,
        from_address=value.get("from_address") or user,
        security=value.get("security") or "starttls",
    )


def get_invite_base_url(db: Session) -> str | None:
    """ที่อยู่ระบบสำหรับสร้างลิงก์คำเชิญ: ค่าจากหน้าเว็บ > PUBLIC_ADMIN_URL/PUBLIC_IP ใน .env"""
    return _setting_value(db, INVITE_SETTING_KEY).get("base_url") or get_settings().public_admin_url


def get_default_expiry_days(db: Session) -> int:
    days = _setting_value(db, INVITE_SETTING_KEY).get("default_expiry_days") or DEFAULT_EXPIRY_DAYS
    return max(1, min(int(days), MAX_EXPIRY_DAYS))
