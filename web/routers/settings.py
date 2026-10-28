"""ตั้งค่าระบบ: จำกัด IP เข้าหลังบ้าน (NFR-12, P4) + อีเมลและลิงก์คำเชิญ (SMTP)"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from core.app_settings import (
    DISPLAY_SETTING_KEY,
    HEALTH_LIMITS,
    HEALTH_SETTING_KEY,
    LOGO_MAX_BYTES,
    PUBLIC_TOGGLES,
    detect_logo_type,
    logo_dir,
    load_display,
    load_health,
    save_setting,
)
from core.backup import backup_hour, backup_keep, copy_dir, days_covered, list_backups, read_status, run_backup
from core.config import get_settings as get_app_settings
from core.config import local_utc_offset_hours
from core.db import get_db
from core.models import AuditLog, Camera, Setting
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


# ---------- สำรองข้อมูล (NFR-7, TOR 5.1) ----------

def _backup_dir():
    return get_app_settings().data_dir / "backups"


@router.get("/backup")
def get_backup_status(_admin: CurrentUser = Depends(require_admin)) -> dict:
    """สถานะการสำรองล่าสุด + รายการไฟล์สำรอง (worker สำรองให้อัตโนมัติทุกวัน)"""
    files = list_backups(_backup_dir())
    offsite = copy_dir()
    return {
        "status": read_status(_backup_dir()),
        "files": [{"name": f.name, "size": f.size, "created_at": f.created_at.isoformat()} for f in files],
        "keep": backup_keep(),
        "hour": backup_hour(),
        "days_covered": days_covered(files),
        "copy_dir": str(offsite) if offsite else None,
    }


@router.post("/backup/run")
def run_backup_now(
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """สำรองทันที เช่น ก่อนอัปเดตระบบหรือก่อนแก้ค่าครั้งใหญ่"""
    local_now = datetime.utcnow() + timedelta(hours=local_utc_offset_hours())
    status_ = run_backup(get_app_settings().db_path, _backup_dir(), local_now, reason=f"manual:{admin.username}")
    db.add(AuditLog(user_id=admin.id, action="backup_now", target=status_.get("file"),
                    detail={"ok": status_.get("ok"), "message": status_.get("message")}))
    db.commit()
    if not status_.get("ok"):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, status_.get("message", "สำรองไม่สำเร็จ"))
    return status_


# ---------- ตรวจความปลอดภัยตาม TOR 5.1 (หน้าตั้งค่า → ความปลอดภัย) ----------

@router.get("/security-status")
def security_status(
    request: Request, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
) -> list[dict]:
    """รายการตรวจ TOR 5.1 แบบสด — ใช้ประกอบการตรวจรับ"""
    from web.routers.public import RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS

    app_settings = get_app_settings()
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").split(":")[0]
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host_is_ip = _is_valid_ip_or_cidr(host) if host else True
    allow = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
    allow_value = allow.value if allow else {}
    files = list_backups(_backup_dir())
    last = read_status(_backup_dir()) or {}

    def item(key: str, title: str, ok: bool, detail: str, warn: bool = False) -> dict:
        return {"key": key, "title": title, "state": "ok" if ok else ("warn" if warn else "fail"), "detail": detail}

    return [
        item("login", "หลังบ้านต้องเข้าสู่ระบบด้วยชื่อผู้ใช้และรหัสผ่าน", True,
             "ทุก API หลังบ้านตรวจ session · ผิดรหัส 5 ครั้งล็อก 15 นาที · บันทึกการเข้าสู่ระบบไม่สำเร็จ"),
        item("ip", "จำกัด IP ที่เข้าหลังบ้านได้ผ่านหน้าตั้งค่า", bool(allow_value.get("enabled") and allow_value.get("ips")),
             "เปิดใช้อยู่ " + str(len(allow_value.get("ips", []))) + " รายการ" if allow_value.get("enabled")
             else "มีฟังก์ชันแล้ว แต่ยังไม่ได้เปิดใช้ (แท็บ \"จำกัด IP\")", warn=True),
        item("camera_pw", "รหัสผ่านกล้องเก็บแบบเข้ารหัส", len(app_settings.fernet_key) >= 40 and app_settings.fernet_key != "change-me",
             "เข้ารหัสด้วย Fernet (AES-128) คีย์อยู่ใน .env ไม่อยู่ในฐานข้อมูล" if len(app_settings.fernet_key) >= 40
             else "ยังไม่ได้ตั้ง FERNET_KEY ใน .env"),
        item("secret", "คีย์เซ็นคุกกี้เข้าสู่ระบบ (SECRET_KEY)", len(app_settings.secret_key) >= 32 and app_settings.secret_key != "change-me",
             "ตั้งค่าแล้ว" if len(app_settings.secret_key) >= 32 else "SECRET_KEY สั้นหรือยังเป็นค่าตัวอย่าง"),
        item("https", "เชื่อมต่อผ่าน HTTPS ด้วยใบรับรองที่ถูกต้อง", scheme == "https" and not host_is_ip,
             f"กำลังใช้ {scheme}://{host} — ใบรับรองของโดเมน (Let's Encrypt)" if scheme == "https" and not host_is_ip
             else f"กำลังใช้ {scheme}://{host} — เข้าผ่าน IP ใช้ใบรับรองที่ระบบออกเอง เบราว์เซอร์จะเตือน ต้องเข้าผ่านโดเมน (ดู README หัวข้อ HTTPS)",
             warn=True),
        item("rate", "จำกัดอัตราการเรียกหน้าสาธารณะ (Rate limit)", True,
             f"ไม่เกิน {RATE_LIMIT_MAX_REQUESTS} ครั้ง / {RATE_LIMIT_WINDOW_SECONDS} วินาที ต่อ IP (เกินได้รับ HTTP 429) + cache 10 วินาที"),
        item("backup", "สำรองฐานข้อมูลอัตโนมัติทุกวัน เก็บไม่น้อยกว่า 7 วัน", bool(last.get("ok")) and days_covered(files) >= 7,
             (f"ล่าสุด {str(last.get('time', '-')).replace('T', ' ')} · มีไฟล์สำรอง {days_covered(files)} วัน (เก็บ {backup_keep()} ชุด)"
              if last.get("ok") else f"ล่าสุด: {last.get('message', 'ยังไม่เคยสำรอง')}"),
             warn=bool(last.get("ok"))),
    ]


# ---------- ระบบและการแสดงผล (ชื่อหน่วยงาน, สวิตช์แสดง/ซ่อน, การตรวจสถานะกล้อง) ----------

class PublicDisplayIn(BaseModel):
    lang_switch: bool = True
    directions: bool = True
    nearby_sort: bool = True
    free_list: bool = True
    slot_map: bool = True
    peak_chart: bool = True


class DisplayIn(BaseModel):
    org_name: str = Field("", max_length=120)
    system_title: str = Field("", max_length=200)
    show_system_title: bool = True
    show_server_address: bool = True
    show_sidebar_footer: bool = True
    public: PublicDisplayIn = PublicDisplayIn()


class HealthIn(BaseModel):
    moved_check_enabled: bool = True
    moved_check_interval_min: int = Field(10, ge=HEALTH_LIMITS["moved_check_interval_min"][0], le=HEALTH_LIMITS["moved_check_interval_min"][1])
    moved_threshold_px: int = Field(50, ge=HEALTH_LIMITS["moved_threshold_px"][0], le=HEALTH_LIMITS["moved_threshold_px"][1])


class SystemSettingsIn(BaseModel):
    display: DisplayIn
    health: HealthIn


def _system_out(db: Session) -> dict:
    return {"display": load_display(db), "health": load_health(db), "public_keys": list(PUBLIC_TOGGLES)}


@router.get("/system")
def get_system_settings(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)) -> dict:
    return _system_out(db)


@router.put("/system")
def update_system_settings(
    data: SystemSettingsIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    display = data.display.model_dump()
    display["org_name"] = display["org_name"].strip()
    display["system_title"] = display["system_title"].strip()
    health = data.health.model_dump()
    before = _system_out(db)
    display["logo_file"] = before["display"]["logo_file"]  # โลโก้แก้ผ่านปุ่มอัปโหลดเท่านั้น
    display["logo_version"] = before["display"]["logo_version"]
    save_setting(db, DISPLAY_SETTING_KEY, display)
    save_setting(db, HEALTH_SETTING_KEY, health)
    changed = [k for k in display if before["display"].get(k) != display[k]]
    changed += [k for k in health if before["health"].get(k) != health[k]]
    db.add(AuditLog(user_id=admin.id, action="update_system_settings", target="settings:system", detail={"fields": changed}))
    db.commit()
    return _system_out(db)


@router.post("/system/check-now")
def check_cameras_now(
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """ให้ worker ตรวจกล้องถูกขยับทุกตัวในรอบตรวจจับถัดไป (ไม่ต้องรอครบรอบปกติ)"""
    result = db.execute(update(Camera).where(Camera.enabled.is_(True)).values(last_health_check_at=None))
    db.add(AuditLog(user_id=admin.id, action="check_cameras_now", target="cameras", detail={"rows": result.rowcount}))
    db.commit()
    return {"ok": True, "cameras": result.rowcount}


@router.post("/system/logo")
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """อัปโหลดโลโก้ (PNG/JPG/WebP ไม่เกิน 1 MB) แสดงแทนไอคอน P ในแถบเมนูและหน้าเข้าสู่ระบบ"""
    data = await file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ไฟล์ใหญ่เกิน 1 MB — ย่อขนาดภาพก่อน (แนะนำ 256×256 พิกเซล)")
    ext = detect_logo_type(data)
    if ext is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "รองรับเฉพาะไฟล์ภาพ PNG, JPG หรือ WebP")
    folder = logo_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("logo.*"):
        old.unlink(missing_ok=True)
    (folder / f"logo.{ext}").write_bytes(data)

    display = load_display(db)
    display["logo_file"] = f"logo.{ext}"
    display["logo_version"] = int(datetime.utcnow().timestamp())
    save_setting(db, DISPLAY_SETTING_KEY, display)
    db.add(AuditLog(user_id=admin.id, action="update_logo", target="settings:logo", detail={"format": ext}))
    db.commit()
    return _system_out(db)


@router.delete("/system/logo")
def delete_logo(
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """กลับไปใช้โลโก้ตั้งต้น"""
    for old in logo_dir().glob("logo.*"):
        old.unlink(missing_ok=True)
    display = load_display(db)
    display["logo_file"] = ""
    display["logo_version"] = int(datetime.utcnow().timestamp())
    save_setting(db, DISPLAY_SETTING_KEY, display)
    db.add(AuditLog(user_id=admin.id, action="delete_logo", target="settings:logo", detail=None))
    db.commit()
    return _system_out(db)
