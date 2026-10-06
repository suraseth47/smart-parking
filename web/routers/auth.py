"""login/logout และ whoami (FR-40..43)"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, User
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
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == data.username))
    invalid_credentials = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
    )

    if user is None or not user.is_active:
        raise invalid_credentials

    if user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"บัญชีถูกล็อกชั่วคราว กรุณาลองใหม่หลัง {user.locked_until.strftime('%H:%M')}",
        )

    if not verify_password(data.password, user.password_hash):
        _register_failed_login(db, user)
        raise invalid_credentials

    _register_successful_login(db, user)
    _set_auth_cookies(response, user_id=user.id, role=user.role.value)
    return {"username": user.username, "role": user.role.value}


@router.post("/logout")
def logout(response: Response, _user: CurrentUser = Depends(get_current_user)) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    return {"ok": True}


@router.get("/whoami")
def whoami(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"username": user.username, "role": user.role}


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
