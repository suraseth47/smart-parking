"""อ่านค่า config จาก .env ให้ web และ worker ใช้ร่วมกัน"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class Settings:
    domain: str
    acme_email: str
    site_name_th: str
    site_name_en: str
    secret_key: str
    fernet_key: str
    admin_allow_ips: list[str]
    tz: str
    data_dir: Path
    db_path: Path


@lru_cache
def get_settings() -> Settings:
    """โหลด .env (ครั้งแรกครั้งเดียว) แล้วคืนค่า Settings"""
    # ระบุ encoding="utf-8" ชัดเจน ไม่งั้น Windows ไทยจะอ่านด้วย cp874 แล้วค่าภาษาไทยเพี้ยน
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8")
    allow_ips_raw = os.environ.get("ADMIN_ALLOW_IPS", "")

    return Settings(
        domain=os.environ.get("DOMAIN", "localhost"),
        acme_email=os.environ.get("ACME_EMAIL", ""),
        site_name_th=os.environ.get("SITE_NAME_TH", "ลานจอดรถ"),
        site_name_en=os.environ.get("SITE_NAME_EN", "Parking"),
        secret_key=os.environ.get("SECRET_KEY", ""),
        fernet_key=os.environ.get("FERNET_KEY", ""),
        admin_allow_ips=[ip.strip() for ip in allow_ips_raw.split(",") if ip.strip()],
        tz=os.environ.get("TZ", "Asia/Bangkok"),
        data_dir=DATA_DIR,
        db_path=DATA_DIR / "app.db",
    )
