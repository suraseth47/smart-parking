"""Jinja2 templates environment ใช้ร่วมกันทุก router ที่ render HTML (แยกไฟล์กัน circular import กับ web.main)"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from core.config import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def branding() -> dict:
    """ชื่อระบบ/หน่วยงานที่แสดงในแถบเมนูและหัวเว็บหลังบ้าน (ตั้งใน .env: SYSTEM_TITLE, ORG_NAME)"""
    settings = get_settings()
    return {"system_title": settings.system_title, "org_name": settings.org_name}


templates.env.globals["branding"] = branding
