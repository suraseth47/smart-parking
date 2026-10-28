"""login/logout และ whoami (FR-40..43)"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import local_utc_offset_hours
from core.db import get_db
from core.models import AuditLog, User
from core.permissions import effective_permissions
from core.security import verify_password
from web.deps import CurrentUser, get_current_user
from web.session import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_cookie,
    generate_csrf_token,
)

router = APIRouter(prefix="/api/admin", tags=["auth"])

LOCKOUT_THRESHOLD = 5  # ผิดครบเท่านี้ครั้งแล้วล็อกบัญชี (FR-41)
LOCKOUT_MINUTES = 15


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    login_name = data.username.strip()
    if "@" in login_name:
        # เข้าสู่ระบบด้วยอีเมลแทนชื่อผู้ใช้ได้ (อีเมลไม่ซ้ำกันในระบบ)
        user = db.scalar(select(User).where(func.lower(User.email) == login_name.lower()))
    else:
        user = db.scalar(select(User).where(User.username == login_name))
    invalid_credentials = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
    )

    client_ip = request.client.host if request.client else None

    if user is None or not user.is_active:
        _audit_failed_login(db, None, login_name, client_ip, "unknown_or_inactive")
        raise invalid_credentials

    if user.locked_until and user.locked_until > datetime.utcnow():
        _audit_failed_login(db, user.id, login_name, client_ip, "locked")
        local_unlock = user.locked_until + timedelta(hours=local_utc_offset_hours())
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"บัญชีถูกล็อกชั่วคราว กรุณาลองใหม่หลัง {local_unlock.strftime('%H:%M')} น.",
        )

    if not verify_password(data.password, user.password_hash):
        _audit_failed_login(db, user.id, login_name, client_ip, "wrong_password", commit=False)
        _register_failed_login(db, user)
        raise invalid_credentials

    _register_successful_login(db, user)
    _set_auth_cookies(response, user_id=user.id, role=user.role.value)
    role = user.role.value
    return {"username": user.username, "role": role, "permissions": effective_permissions(role, user.permissions)}


@router.post("/logout")
def logout(response: Response, _user: CurrentUser = Depends(get_current_user)) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    return {"ok": True}


@router.get("/whoami")
def whoami(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role, "permissions": user.permissions,
            "site_ids": user.site_ids}


def _audit_failed_login(db: Session, user_id: int | None, login_name: str, ip: str | None, reason: str, commit: bool = True) -> None:
    """บันทึกการเข้าสู่ระบบไม่สำเร็จ (ตรวจย้อนหลังได้ว่ามีคนพยายามเดารหัสหรือไม่) — ไม่เก็บรหัสผ่านที่พิมพ์"""
    db.add(AuditLog(user_id=user_id, action="login_failed", target=login_name[:100], detail={"ip": ip, "reason": reason}))
    if commit:
        db.commit()


def _register_failed_login(db: Session, user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= LOCKOUT_THRESHOLD:
        user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
    db.commit()


def _register_successful_login(db: Session, user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    db.add(AuditLog(user_id=user.id, action="login", target=user.username))
    db.commit()


def _set_auth_cookies(response: Response, user_id: int, role: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie(user_id, role),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_csrf_token(),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,  # ฝั่ง Alpine.js ต้องอ่านค่านี้ไปแนบเป็น header ตอนส่งฟอร์ม
        secure=True,
        samesite="lax",
    )
