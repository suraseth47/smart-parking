"""ผู้ใช้และคำเชิญ: เชิญด้วยลิงก์/อีเมล, เพิ่มผู้ใช้โดยตรง, กำหนดบทบาทและสิทธิ์รายเมนู,
ปิดบัญชี, ออกลิงก์ตั้งรหัสผ่านใหม่

ฝั่ง Admin: /api/admin/users*, /api/admin/invitations*, /api/admin/permissions
ฝั่งผู้รับคำเชิญ (ไม่ต้อง login): /api/invite/{token} — ลิงก์ใช้ได้ครั้งเดียวและมีวันหมดอายุ
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_db
from core.invitations import (
    ALLOWED_EXPIRY_HOURS,
    ROLE_LABELS_TH,
    can_change_admin,
    generate_token,
    hash_token,
    invitation_status,
    validate_email,
    validate_password,
    validate_username,
)
from core.models import AuditLog, Invitation, InvitationPurpose, User, UserRole
from core.permissions import PERMISSIONS, ROLE_MAX, effective_permissions, normalize_permissions
from core.security import hash_password
from web.deps import CurrentUser, require_admin, verify_csrf
from web.templates_env import templates

admin_router = APIRouter(prefix="/api/admin", tags=["users"])
public_router = APIRouter(prefix="/api/invite", tags=["invite"])
page_router = APIRouter(tags=["invite-page"])

PERMISSION_LABELS = {key: th for key, th, _ in PERMISSIONS}


@page_router.get("/invite/{token}", response_class=HTMLResponse)
def invite_page(request: Request, token: str):
    """หน้าเปิดลิงก์คำเชิญ (หน้าเว็บอ่าน token จากที่อยู่เอง แล้วตรวจผ่าน API) — ไม่ต้อง login"""
    response = templates.TemplateResponse(request, "invite.html")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # ไม่ส่งลิงก์ที่มี token ต่อไปเว็บอื่น
    return response


# ---------- schemas ----------

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None
    email: str | None
    role: str
    permissions: list[str]  # สิทธิ์ที่ใช้ได้จริง
    custom_permissions: bool  # True = ถูกติ๊กลดจากสิทธิ์เต็มของบทบาท
    is_active: bool
    created_at: datetime | None
    last_login_at: datetime | None
    locked: bool


class UserCreateIn(BaseModel):
    username: str
    full_name: str | None = None
    email: str | None = None
    password: str
    password_confirm: str
    role: UserRole
    permissions: list[str] | None = None


class UserUpdateIn(BaseModel):
    role: UserRole | None = None
    permissions: list[str] | None = None  # ส่ง null = กลับไปใช้สิทธิ์ตามบทบาท
    is_active: bool | None = None
    full_name: str | None = None
    email: str | None = None


class InvitationIn(BaseModel):
    role: UserRole
    method: Literal["email", "link"] = "link"
    full_name: str | None = None
    email: str | None = None
    permissions: list[str] | None = None
    message: str | None = None
    expires_hours: int = 72


class InvitationOut(BaseModel):
    id: int
    purpose: str
    method: str
    role: str
    permissions: list[str]
    custom_permissions: bool
    full_name: str | None
    email: str | None
    message: str | None
    target_username: str | None
    created_by: str | None
    created_at: datetime | None
    expires_at: datetime
    accepted_at: datetime | None
    status: str
    accepted_username: str | None


class InvitationCreatedOut(BaseModel):
    invitation: InvitationOut
    url: str  # แสดงครั้งเดียวตอนสร้าง — ระบบไม่ได้เก็บ token จริงไว้


class InviteInfoOut(BaseModel):
    purpose: str
    role: str
    role_label: str
    permission_labels: list[str]
    full_name: str | None
    email: str | None
    message: str | None
    username: str | None  # มีค่าเมื่อเป็นลิงก์ตั้งรหัสผ่านใหม่ของผู้ใช้เดิม
    expires_at: datetime


class AcceptIn(BaseModel):
    username: str | None = None
    password: str
    password_confirm: str


# ---------- helpers ----------

def _clean(text: str | None, max_len: int | None = None) -> str | None:
    text = (text or "").strip()
    if max_len:
        text = text[:max_len]
    return text or None


def _user_out(user: User, now: datetime) -> UserOut:
    role = user.role.value
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=role,
        permissions=effective_permissions(role, user.permissions),
        custom_permissions=role != "admin" and user.permissions is not None,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        locked=bool(user.locked_until and user.locked_until > now),
    )


def _invitation_out(db: Session, inv: Invitation, now: datetime) -> InvitationOut:
    def username_of(user_id: int | None) -> str | None:
        user = db.get(User, user_id) if user_id else None
        return user.username if user else None

    role = inv.role.value
    return InvitationOut(
        id=inv.id,
        purpose=inv.purpose.value,
        method=inv.method or "link",
        role=role,
        permissions=effective_permissions(role, inv.permissions),
        custom_permissions=role != "admin" and inv.permissions is not None,
        full_name=inv.full_name,
        email=inv.email,
        message=inv.message,
        target_username=username_of(inv.target_user_id),
        created_by=username_of(inv.created_by),
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        status=invitation_status(inv.accepted_at, inv.revoked_at, inv.expires_at, now),
        accepted_username=username_of(inv.accepted_user_id),
    )


def _invite_url(request: Request, token: str) -> str:
    """ลิงก์ที่ส่งให้ผู้รับ — ใช้ที่อยู่หลังบ้านจากภายนอกเสมอ (เปิดจากที่ไหนก็ได้)"""
    base = get_settings().public_admin_url or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


def _active_admin_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )


def _check_email(db: Session, email: str | None, exclude_user_id: int | None = None) -> None:
    """อีเมลไม่บังคับ แต่ถ้าใส่ต้องถูกรูปแบบและไม่ซ้ำ (เพราะใช้เข้าสู่ระบบแทนชื่อผู้ใช้ได้)"""
    error = validate_email(email)
    if error:
        raise HTTPException(422, error)
    if email:
        query = select(User).where(func.lower(User.email) == email.lower())
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        if db.scalar(query):
            raise HTTPException(status.HTTP_409_CONFLICT, "อีเมลนี้มีผู้ใช้อื่นใช้แล้ว")


def _check_new_username(db: Session, username: str) -> None:
    error = validate_username(username)
    if error:
        raise HTTPException(422, error)
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "ชื่อผู้ใช้นี้มีคนใช้แล้ว กรุณาเลือกชื่ออื่น")


def _new_invitation(
    db: Session, request: Request, admin: CurrentUser, *, purpose: InvitationPurpose, role: UserRole,
    full_name: str | None, email: str | None, target_user_id: int | None, expires_hours: int,
    method: str = "link", permissions: list[str] | None = None, message: str | None = None,
) -> InvitationCreatedOut:
    if expires_hours not in ALLOWED_EXPIRY_HOURS:
        raise HTTPException(422, "อายุลิงก์ต้องเป็น 24, 72 หรือ 168 ชั่วโมง")
    now = datetime.utcnow()
    token = generate_token()
    inv = Invitation(
        token_hash=hash_token(token),
        purpose=purpose,
        role=role,
        permissions=permissions,
        method=method,
        message=message,
        full_name=full_name,
        email=email,
        target_user_id=target_user_id,
        created_by=admin.id,
        created_at=now,
        expires_at=now + timedelta(hours=expires_hours),
    )
    db.add(inv)
    db.flush()
    db.add(
        AuditLog(
            user_id=admin.id,
            action="create_invitation" if purpose == InvitationPurpose.INVITE else "create_password_reset",
            target=(email or full_name or "")[:100] or None,
            detail={"invitation_id": inv.id, "role": role.value, "method": method,
                    "permissions": permissions, "expires_hours": expires_hours},
        )
    )
    db.commit()
    db.refresh(inv)
    return InvitationCreatedOut(invitation=_invitation_out(db, inv, now), url=_invite_url(request, token))


def _usable_invitation(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบลิงก์นี้ หรือลิงก์ไม่ถูกต้อง")
    state = invitation_status(inv.accepted_at, inv.revoked_at, inv.expires_at, datetime.utcnow())
    messages = {
        "accepted": "ลิงก์นี้ถูกใช้ไปแล้ว",
        "revoked": "ลิงก์นี้ถูกยกเลิกแล้ว กรุณาติดต่อผู้ดูแลระบบ",
        "expired": "ลิงก์นี้หมดอายุแล้ว กรุณาขอลิงก์ใหม่จากผู้ดูแลระบบ",
    }
    if state in messages:
        raise HTTPException(status.HTTP_410_GONE, messages[state])
    return inv


# ---------- Admin: รายการสิทธิ์ (ให้หน้าเว็บใช้สร้างช่องติ๊ก) ----------

@admin_router.get("/permissions")
def list_permissions(_admin: CurrentUser = Depends(require_admin)) -> dict:
    return {
        "permissions": [{"key": k, "label": th, "label_en": en} for k, th, en in PERMISSIONS],
        "role_max": {role: list(keys) for role, keys in ROLE_MAX.items()},
    }


# ---------- Admin: ผู้ใช้ ----------

@admin_router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    now = datetime.utcnow()
    return [_user_out(u, now) for u in db.scalars(select(User).order_by(User.id)).all()]


@admin_router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreateIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """เพิ่มผู้ใช้โดยตรง — Admin ตั้งรหัสผ่านให้ (ถ้าอยากให้ผู้ใช้ตั้งเอง ใช้คำเชิญแทน)"""
    username = data.username.strip()
    _check_new_username(db, username)
    email = _clean(data.email)
    _check_email(db, email)
    error = validate_password(data.password, data.password_confirm)
    if error:
        raise HTTPException(422, error)
    user = User(
        username=username,
        password_hash=hash_password(data.password),
        role=data.role,
        permissions=normalize_permissions(data.role.value, data.permissions),
        is_active=True,
        full_name=_clean(data.full_name, 100),
        email=email,
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_user", target=user.username,
                    detail={"role": user.role.value, "permissions": user.permissions}))
    db.commit()
    db.refresh(user)
    return _user_out(user, datetime.utcnow())


@admin_router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdateIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบผู้ใช้นี้")
    fields = data.model_fields_set
    new_role = data.role if "role" in fields else None
    new_active = data.is_active if "is_active" in fields else None

    if user.id == admin.id and (
        (new_role is not None and new_role != UserRole.ADMIN) or new_active is False
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "เปลี่ยนบทบาทหรือปิดบัญชีของตัวเองไม่ได้")
    is_active_admin = user.role == UserRole.ADMIN and user.is_active
    if not can_change_admin(
        _active_admin_count(db), is_active_admin, new_role.value if new_role else None, new_active
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ต้องมีผู้ดูแลระบบที่ใช้งานได้อย่างน้อย 1 คน")

    detail: dict = {}
    if new_role is not None and new_role != user.role:
        user.role = new_role
        detail["role"] = new_role.value
        if "permissions" not in fields:
            user.permissions = None  # เปลี่ยนบทบาท = เริ่มจากสิทธิ์เต็มของบทบาทใหม่
    if "permissions" in fields:
        user.permissions = normalize_permissions(user.role.value, data.permissions)
        detail["permissions"] = user.permissions
    if new_active is not None:
        user.is_active = new_active
        detail["is_active"] = new_active
        if new_active:
            user.failed_logins = 0
            user.locked_until = None  # เปิดบัญชีคืน = ปลดล็อกด้วย
    if "email" in fields:
        user.email = _clean(data.email)
        _check_email(db, user.email, exclude_user_id=user.id)
        detail["email"] = user.email
    if "full_name" in fields:
        user.full_name = _clean(data.full_name, 100)
        detail["full_name"] = user.full_name

    db.add(AuditLog(user_id=admin.id, action="update_user", target=user.username, detail=detail))
    db.commit()
    db.refresh(user)
    return _user_out(user, datetime.utcnow())


@admin_router.post("/users/{user_id}/password-reset", response_model=InvitationCreatedOut)
def create_password_reset(
    user_id: int,
    request: Request,
    expires_hours: int = 24,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """ออกลิงก์ให้ผู้ใช้เดิมตั้งรหัสผ่านใหม่เอง (Admin ไม่ต้องรู้รหัสผ่านของใคร)"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบผู้ใช้นี้")
    return _new_invitation(
        db, request, admin, purpose=InvitationPurpose.RESET, role=user.role,
        full_name=user.full_name or user.username, email=user.email,
        target_user_id=user.id, expires_hours=expires_hours,
        method="email" if user.email else "link", permissions=user.permissions,
    )


# ---------- Admin: คำเชิญ ----------

@admin_router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    now = datetime.utcnow()
    rows = db.scalars(select(Invitation).order_by(Invitation.id.desc()).limit(50)).all()
    return [_invitation_out(db, inv, now) for inv in rows]


@admin_router.post("/invitations", response_model=InvitationCreatedOut, status_code=status.HTTP_201_CREATED)
def create_invitation(
    data: InvitationIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    email = _clean(data.email)
    if data.method == "email" and not email:
        raise HTTPException(422, "ส่งทางอีเมลต้องใส่อีเมลผู้รับ")
    _check_email(db, email)
    return _new_invitation(
        db, request, admin, purpose=InvitationPurpose.INVITE, role=data.role,
        full_name=_clean(data.full_name, 100), email=email, target_user_id=None,
        expires_hours=data.expires_hours, method=data.method,
        permissions=normalize_permissions(data.role.value, data.permissions),
        message=_clean(data.message, 500),
    )


@admin_router.delete("/invitations/{invitation_id}", response_model=InvitationOut)
def revoke_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบคำเชิญนี้")
    now = datetime.utcnow()
    if invitation_status(inv.accepted_at, inv.revoked_at, inv.expires_at, now) == "pending":
        inv.revoked_at = now
        db.add(AuditLog(user_id=admin.id, action="revoke_invitation", detail={"invitation_id": inv.id}))
        db.commit()
    return _invitation_out(db, inv, now)


# ---------- ผู้รับคำเชิญ (ไม่ต้อง login) ----------

@public_router.get("/{token}", response_model=InviteInfoOut)
def get_invite_info(token: str, db: Session = Depends(get_db)):
    inv = _usable_invitation(db, token)
    target = db.get(User, inv.target_user_id) if inv.target_user_id else None
    role = inv.role.value
    return InviteInfoOut(
        purpose=inv.purpose.value,
        role=role,
        role_label=ROLE_LABELS_TH.get(role, role),
        permission_labels=[PERMISSION_LABELS[k] for k in effective_permissions(role, inv.permissions)],
        full_name=inv.full_name,
        email=inv.email,
        message=inv.message,
        username=target.username if target else None,
        expires_at=inv.expires_at,
    )


@public_router.post("/{token}/accept")
def accept_invite(token: str, data: AcceptIn, db: Session = Depends(get_db)) -> dict:
    inv = _usable_invitation(db, token)
    error = validate_password(data.password, data.password_confirm)
    if error:
        raise HTTPException(422, error)
    now = datetime.utcnow()

    if inv.purpose == InvitationPurpose.RESET:
        user = db.get(User, inv.target_user_id) if inv.target_user_id else None
        if user is None:
            raise HTTPException(status.HTTP_410_GONE, "ไม่พบบัญชีผู้ใช้ของลิงก์นี้แล้ว")
        user.password_hash = hash_password(data.password)
        user.failed_logins = 0
        user.locked_until = None
        action = "password_reset_done"
    else:
        username = (data.username or "").strip()
        _check_new_username(db, username)
        _check_email(db, inv.email)  # กันกรณีมีคนใช้อีเมลนี้ไปแล้วหลังส่งคำเชิญ
        user = User(
            username=username,
            password_hash=hash_password(data.password),
            role=inv.role,
            permissions=inv.permissions,
            is_active=True,
            full_name=inv.full_name,
            email=inv.email,
        )
        db.add(user)
        db.flush()
        action = "accept_invitation"

    inv.accepted_at = now
    inv.accepted_user_id = user.id
    db.add(AuditLog(user_id=user.id, action=action, target=user.username, detail={"invitation_id": inv.id}))
    db.commit()
    return {"username": user.username, "role": user.role.value}
