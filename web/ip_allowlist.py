"""จำกัดการเข้าถึงหลังบ้านตาม IP ที่ Admin กำหนดเอง (NFR-12, P4)

หน้า login ยกเว้นจากการบล็อกเสมอ (เข้าได้จากทุก IP) เพื่อไม่ให้ Admin ล็อกตัวเอง
ออกจากหลังบ้านโดยสมบูรณ์หากตั้งค่า allowlist ผิดพลาด — แต่ action อื่นทั้งหมดหลัง
login (รวม whoami) ยังถูกบล็อกตามปกติถ้า IP ไม่อยู่ใน allowlist
"""
from __future__ import annotations

import ipaddress

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.db import SessionLocal
from core.models import Setting

IP_ALLOWLIST_SETTING_KEY = "ip_allowlist"
RESTRICTED_PATH_PREFIXES = ("/admin", "/api/admin")
LOGIN_PATHS = ("/admin/login", "/api/admin/login")


def is_ip_allowed(client_ip: str, allowlist: dict) -> bool:
    """pure function: ตรวจว่า IP นี้ผ่านเกณฑ์ allowlist หรือไม่

    ปิดใช้ (enabled=False) หรือยังไม่ตั้งรายการเลย -> ผ่านเสมอ (กันตั้งค่าแล้วล็อกตัวเองทันที)
    """
    if not allowlist or not allowlist.get("enabled"):
        return True
    entries = allowlist.get("ips") or []
    if not entries:
        return True
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in entries:
        try:
            if ip_obj in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """เช็คทุก request ที่ path ขึ้นต้นด้วย /admin หรือ /api/admin (ยกเว้นหน้า login)"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(RESTRICTED_PATH_PREFIXES) or path in LOGIN_PATHS:
            return await call_next(request)

        db = SessionLocal()
        try:
            setting = db.get(Setting, IP_ALLOWLIST_SETTING_KEY)
            allowlist = setting.value if setting else {}
        finally:
            db.close()

        client_ip = request.client.host if request.client else ""
        if not is_ip_allowed(client_ip, allowlist):
            return JSONResponse({"detail": "IP นี้ไม่ได้รับอนุญาตให้เข้าหลังบ้าน"}, status_code=403)
        return await call_next(request)
