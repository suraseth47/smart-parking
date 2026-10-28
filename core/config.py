"""อ่านค่า config จาก .env ให้ web และ worker ใช้ร่วมกัน"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_DETECTOR_MODEL = "yolox_s.onnx"


@dataclass
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    from_address: str
    security: str  # "starttls" (พอร์ต 587) | "ssl" (พอร์ต 465) | "none"

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)


@dataclass
class Settings:
    domain: str
    acme_email: str
    site_name_th: str
    site_name_en: str
    secret_key: str
    fernet_key: str
    tz: str
    data_dir: Path
    db_path: Path
    detector_model: str  # ชื่อไฟล์โมเดลในโฟลเดอร์ models/ (ตั้งใน .env: DETECTOR_MODEL)
    public_admin_url: str | None  # ที่อยู่หลังบ้านจากภายนอก ใช้สร้างลิงก์คำเชิญ เช่น https://1.2.3.4:8010
    smtp: SmtpSettings  # บัญชีอีเมลที่ระบบใช้ส่งคำเชิญ (ไม่ตั้ง = ส่งเองไม่ได้ ใช้โปรแกรมอีเมลในเครื่องแทน)


@lru_cache
def get_settings() -> Settings:
    """โหลด .env (ครั้งแรกครั้งเดียว) แล้วคืนค่า Settings"""
    # ระบุ encoding="utf-8" ชัดเจน ไม่งั้น Windows ไทยจะอ่านด้วย cp874 แล้วค่าภาษาไทยเพี้ยน
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8")

    return Settings(
        domain=os.environ.get("DOMAIN", "localhost"),
        acme_email=os.environ.get("ACME_EMAIL", ""),
        site_name_th=os.environ.get("SITE_NAME_TH", "ลานจอดรถ"),
        site_name_en=os.environ.get("SITE_NAME_EN", "Parking"),
        secret_key=os.environ.get("SECRET_KEY", ""),
        fernet_key=os.environ.get("FERNET_KEY", ""),
        tz=os.environ.get("TZ", "Asia/Bangkok"),
        data_dir=DATA_DIR,
        db_path=DATA_DIR / "app.db",
        detector_model=os.environ.get("DETECTOR_MODEL", DEFAULT_DETECTOR_MODEL),
        public_admin_url=_public_admin_url(),
        smtp=_smtp_settings(),
    )


def _smtp_settings() -> SmtpSettings:
    """อ่านค่า SMTP_* จาก .env — SMTP_FROM ไม่ตั้งจะใช้ SMTP_USER แทน"""
    user = os.environ.get("SMTP_USER", "").strip()
    port_text = os.environ.get("SMTP_PORT", "587").strip() or "587"
    security = os.environ.get("SMTP_SECURITY", "").strip().lower()
    if security not in ("starttls", "ssl", "none"):
        security = "ssl" if port_text == "465" else "starttls"
    return SmtpSettings(
        host=os.environ.get("SMTP_HOST", "").strip(),
        port=int(port_text) if port_text.isdigit() else 587,
        user=user,
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_address=os.environ.get("SMTP_FROM", "").strip() or user,
        security=security,
    )


def _public_admin_url() -> str | None:
    """PUBLIC_ADMIN_URL ถ้าตั้งไว้ ไม่งั้นประกอบจาก PUBLIC_IP + ADMIN_PUBLIC_PORT (ค่าเดียวกับที่ Caddy ใช้)"""
    explicit = os.environ.get("PUBLIC_ADMIN_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    public_ip = os.environ.get("PUBLIC_IP", "").strip()
    if not public_ip:
        return None
    return f"https://{public_ip}:{os.environ.get('ADMIN_PUBLIC_PORT', '8010').strip()}"


def get_detector_model_path() -> Path:
    """path ของโมเดลที่ตั้งไว้ใน .env — ถ้าไม่มีไฟล์ ให้กลับไปใช้ yolox_s.onnx (ระบบยังทำงานต่อได้)"""
    name = Path(get_settings().detector_model).name  # กันใส่ path แปลกๆ ให้อยู่ใน models/ เสมอ
    path = MODELS_DIR / name
    if path.exists():
        return path
    print(f"[detector] ไม่พบโมเดล {path} ใช้ {DEFAULT_DETECTOR_MODEL} แทน", flush=True)
    return MODELS_DIR / DEFAULT_DETECTOR_MODEL


def local_utc_offset_hours() -> float:
    """offset ของเขตเวลาใน .env (TZ) เทียบ UTC — ฐานข้อมูลเก็บเวลาเป็น UTC ทั้งหมด
    ใช้แปลงเป็นเวลาไทยตอนแสดงผล/ทำรายงาน; อ่านไม่ได้ใช้ +7 (ประเทศไทย)"""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        offset = datetime.now(ZoneInfo(get_settings().tz)).utcoffset()
        return offset.total_seconds() / 3600 if offset is not None else 7.0
    except Exception:
        return 7.0
