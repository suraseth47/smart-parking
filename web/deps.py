"""FastAPI dependency: current_user, require_admin, verify_csrf (FR-40..43)"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import User
from web.session import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, read_session_cookie


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """ตรวจ session cookie แล้วคืนผู้ใช้ปัจจุบัน; โยน 401 ถ้ายังไม่ login"""
    payload = read_session_cookie(request.cookies.get(SESSION_COOKIE_NAME))
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "กรุณาเข้าสู่ระบบ")

    user = db.get(User, payload["user_id"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "กรุณาเข้าสู่ระบบ")

    return CurrentUser(id=user.id, username=user.username, role=user.role.value)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """ใช้กับ endpoint ที่ Admin เท่านั้นทำได้ (เช่น จัดการกล้อง, publish layout)"""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ต้องเป็น Admin เท่านั้น")
    return user


def verify_csrf(request: Request) -> None:
    """ป้องกัน CSRF แบบ double-submit cookie: header X-CSRF-Token ต้องตรงกับคุกกี้"""
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token ไม่ถูกต้อง")
