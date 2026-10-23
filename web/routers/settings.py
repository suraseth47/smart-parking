"""ตั้งค่าระบบ: จำกัด IP เข้าหลังบ้าน (NFR-12, P4) + อีเมลและลิงก์คำเชิญ (SMTP)"""
from __future__ import annotations

import ipaddress
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, Setting
from core.security import encrypt_camera_password
from web.deps import CurrentUser, require_admin, verify_csrf
from web.ip_allowlist import IP_ALLOWLIST_SETTING_KEY
from web.mail_config import (
    DEFAULT_EXPIRY_DAYS,
    INVITE_SETTING_KEY,
    MAIL_SETTING_KEY,
    MAX_EXPIRY_DAYS,
    get_default_expiry_days,
    get_invite_base_url,
    smtp_source,
)

router = APIRouter(prefix="/api/admin/settings", tags=["settings"])


class IpAllowlistIn(BaseModel):
    enabled: bool
    ips: list[str]


class IpAllowlistOut(BaseModel):
    enabled: bool
    ips: list[str]


class SettingsOut(BaseModel):
    ip_allowlist: IpAllowlistOut
    your_ip: str


@router.get("", response_model=SettingsOut)
def get_settings_api(
    request: Request, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    setting = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
    value = setting.value if setting else {"enabled": False, "ips": []}
    return SettingsOut(
        ip_allowlist=IpAllowlistOut(enabled=value.get("enabled", False), ips=value.get("ips", [])),
        your_ip=request.client.host if request.client else "",
    )


@router.put("/ip-allowlist", response_model=IpAllowlistOut)
def update_ip_allowlist(
    data: IpAllowlistIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    invalid = [entry for entry in data.ips if not _is_valid_ip_or_cidr(entry)]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"รูปแบบ IP/CIDR ไม่ถูกต้อง: {', '.join(invalid)}")

    setting = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
    value = {"enabled": data.enabled, "ips": data.ips}
    if setting is None:
        setting = Setting(key=IP_ALLOWLIST_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value

    db.add(
        AuditLog(
            user_id=admin.id,
            action="update_ip_allowlist",
            target="settings:ip_allowlist",
            detail=value,
        )
    )
    db.commit()
    return IpAllowlistOut(**value)


def _is_valid_ip_or_cidr(entry: str) -> bool:
    try:
        ipaddress.ip_network(entry, strict=False)
        return True
    except ValueError:
        return False


# ---------- อีเมลและลิงก์คำเชิญ ----------

class MailSettingsIn(BaseModel):
    base_url: str | None = None  # URL ของระบบสำหรับลิงก์คำเชิญ (ว่าง = ใช้ค่าจาก .env)
    default_expiry_days: int = Field(default=DEFAULT_EXPIRY_DAYS, ge=1, le=MAX_EXPIRY_DAYS)
    host: str | None = None  # ว่าง = ปิดการส่งอีเมลจากค่าหน้าเว็บ (ใช้ .env ถ้ามี)
    port: int = Field(default=587, ge=1, le=65535)
    user: str | None = None
    password: str | None = None  # ว่าง/ไม่ส่ง = คงรหัสเดิม
    clear_password: bool = False
    from_address: str | None = None
    security: Literal["starttls", "ssl", "none"] = "starttls"


def _mail_settings_out(db: Session, request: Request) -> dict:
    mail = db.get(Setting, MAIL_SETTING_KEY)
    invite = db.get(Setting, INVITE_SETTING_KEY)
    mail_value = mail.value if mail else {}
    invite_value = invite.value if invite else {}
    return {
        "base_url": invite_value.get("base_url") or "",
        "default_expiry_days": get_default_expiry_days(db),
        "effective_base_url": get_invite_base_url(db) or str(request.base_url).rstrip("/"),
        "host": mail_value.get("host") or "",
        "port": mail_value.get("port") or 587,
        "user": mail_value.get("user") or "",
        "has_password": bool(mail_value.get("password_enc")),
        "from_address": mail_value.get("from_address") or "",
        "security": mail_value.get("security") or "starttls",
        "source": smtp_source(db),
    }


@router.get("/mail")
def get_mail_settings(request: Request, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    """ค่าอีเมลและลิงก์คำเชิญ (ไม่ส่งรหัสผ่านกลับไปหน้าเว็บ บอกแค่ว่ามีบันทึกไว้หรือไม่)"""
    return _mail_settings_out(db, request)


@router.put("/mail")
def update_mail_settings(
    data: MailSettingsIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    base_url = (data.base_url or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://[^\s/]+(:\d+)?(/[^\s]*)?$", base_url):
        raise HTTPException(422, "URL ของระบบต้องขึ้นต้นด้วย http:// หรือ https:// เช่น https://125.26.22.145:8010")
    from_address = (data.from_address or "").strip()
    user = (data.user or "").strip()
    if from_address and "@" not in from_address:
        raise HTTPException(422, 'ชื่อผู้ส่งต้องมีอีเมล เช่น "NASLINK Smart Parking <you@gmail.com>"')

    old = db.get(Setting, MAIL_SETTING_KEY)
    old_value = old.value if old else {}
    password_enc = old_value.get("password_enc")
    if data.clear_password:
        password_enc = None
    elif data.password:
        password_enc = encrypt_camera_password(data.password)  # เข้ารหัสด้วย FERNET_KEY เหมือนรหัสกล้อง

    _save_setting(db, INVITE_SETTING_KEY, {"base_url": base_url, "default_expiry_days": data.default_expiry_days})
    _save_setting(db, MAIL_SETTING_KEY, {
        "host": (data.host or "").strip(),
        "port": data.port,
        "user": user,
        "password_enc": password_enc,
        "from_address": from_address,
        "security": data.security,
    })
    db.add(AuditLog(
        user_id=admin.id, action="update_mail_settings", target="settings:mail",
        # ไม่บันทึกรหัสผ่านลง log บอกแค่ว่าเปลี่ยนหรือไม่
        detail={"host": (data.host or "").strip(), "port": data.port, "user": user, "from": from_address,
                "security": data.security, "base_url": base_url, "default_expiry_days": data.default_expiry_days,
                "password_changed": bool(data.password) or data.clear_password},
    ))
    db.commit()
    return _mail_settings_out(db, request)


def _save_setting(db: Session, key: str, value: dict) -> None:
    setting = db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value
