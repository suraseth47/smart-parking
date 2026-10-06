"""Audit log viewer (FR-43) — Admin เท่านั้น"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, User
from web.deps import CurrentUser, require_admin

router = APIRouter(prefix="/api/admin/audit", tags=["audit"])


class AuditLogOut(BaseModel):
    id: int
    username: str | None
    action: str
    target: str | None
    detail: dict | None
    ts: datetime


@router.get("", response_model=list[AuditLogOut])
def list_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: str | None = None,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    query = (
        select(AuditLog, User.username)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.ts.desc())
    )
    if action:
        query = query.where(AuditLog.action == action)
    rows = db.execute(query.offset(offset).limit(limit)).all()

    return [
        {
            "id": log.id,
            "username": username,
            "action": log.action,
            "target": log.target,
            "detail": log.detail,
            "ts": log.ts,
        }
        for log, username in rows
    ]
