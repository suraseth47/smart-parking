"""Jinja2 templates environment ใช้ร่วมกันทุก router ที่ render HTML (แยกไฟล์กัน circular import กับ web.main)"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from core.app_settings import cached_display

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def branding() -> dict:
    """ชื่อระบบ/หน่วยงาน + สวิตช์แสดง/ซ่อน (ตั้งที่หน้า ตั้งค่าระบบ → ระบบและการแสดงผล)"""
    return cached_display()


templates.env.globals["branding"] = branding
