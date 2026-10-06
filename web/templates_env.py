"""Jinja2 templates environment ใช้ร่วมกันทุก router ที่ render HTML (แยกไฟล์กัน circular import กับ web.main)"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
