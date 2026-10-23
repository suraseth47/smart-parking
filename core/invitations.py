"""คำเชิญผู้ใช้และลิงก์ตั้งรหัสผ่านใหม่ — pure function ไม่ยุ่งกับ DB

หลักความปลอดภัย:
- token สุ่ม 32 ไบต์ อยู่ในลิงก์เท่านั้น ฐานข้อมูลเก็บแค่ SHA-256 ของ token
  (ถ้าฐานข้อมูลหลุด ก็เอาไปเปิดลิงก์ไม่ได้)
- ลิงก์ใช้ได้ครั้งเดียว และหมดอายุตามเวลาที่ตั้ง
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime

TOKEN_BYTES = 32
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ROLE_LABELS_TH = {"admin": "ผู้ดูแลระบบ", "operator": "เจ้าหน้าที่", "viewer": "ผู้ชม"}


def generate_token() -> str:
    """token สำหรับใส่ในลิงก์ (URL-safe)"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """ค่าที่เก็บลงฐานข้อมูลแทนตัว token จริง"""
    return hashlib.sha256(token.encode()).hexdigest()


def invitation_status(
    accepted_at: datetime | None, revoked_at: datetime | None, expires_at: datetime, now: datetime
) -> str:
    """สถานะคำเชิญ: "accepted" | "revoked" | "expired" | "pending" (เรียงตามความสำคัญ)"""
    if accepted_at is not None:
        return "accepted"
    if revoked_at is not None:
        return "revoked"
    if expires_at <= now:
        return "expired"
    return "pending"


def validate_username(username: str) -> str | None:
    """คืนข้อความ error ภาษาไทย หรือ None ถ้าใช้ได้"""
    if not USERNAME_PATTERN.match(username or ""):
        return "ชื่อผู้ใช้ต้องยาว 3–30 ตัว ใช้ได้เฉพาะ a-z, A-Z, 0-9 และ . _ -"
    return None


def validate_password(password: str, password_confirm: str) -> str | None:
    """คืนข้อความ error ภาษาไทย หรือ None ถ้าใช้ได้"""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร"
    if password != password_confirm:
        return "รหัสผ่านทั้งสองช่องไม่ตรงกัน"
    return None


def validate_email(email: str | None) -> str | None:
    """อีเมลไม่บังคับ แต่ถ้าใส่ต้องมีรูปแบบถูกต้อง"""
    if email and not EMAIL_PATTERN.match(email):
        return "รูปแบบอีเมลไม่ถูกต้อง"
    return None


def can_change_admin(
    active_admin_count: int, target_is_active_admin: bool, new_role: str | None, new_is_active: bool | None
) -> bool:
    """กันระบบไม่เหลือ Admin ที่ใช้งานได้เลย (ไม่งั้นจะไม่มีใครจัดการระบบได้อีก)"""
    if not target_is_active_admin:
        return True
    loses_admin = (new_role is not None and new_role != "admin") or new_is_active is False
    return not (loses_admin and active_admin_count <= 1)
