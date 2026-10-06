"""จัดการโซน: CRUD + ปิด/เปิดโซนชั่วคราว (FR-35)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, Zone
from web.deps import CurrentUser, get_current_user, require_admin, verify_csrf

router = APIRouter(prefix="/api/admin/zones", tags=["zones"])


class ZoneIn(BaseModel):
    code: str
    name_th: str
    name_en: str
    floor: str | None = None
    sort_order: int = 0
    expected_slots: int = 0
    is_public: bool = True


class ZoneOut(BaseModel):
    id: int
    code: str
    name_th: str
    name_en: str
    floor: str | None
    sort_order: int
    expected_slots: int
    is_public: bool
    is_closed: bool
    closed_note: str | None

    model_config = {"from_attributes": True}


class ZoneCloseIn(BaseModel):
    is_closed: bool
    closed_note: str | None = None


@router.get("", response_model=list[ZoneOut])
def list_zones(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    return db.scalars(select(Zone).order_by(Zone.sort_order)).all()


@router.post("", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
def create_zone(
    data: ZoneIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    _check_code_not_taken(db, data.code)
    zone = Zone(**data.model_dump())
    db.add(zone)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_zone", target=zone.code))
    db.commit()
    db.refresh(zone)
    return zone


@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(
    zone_id: int, db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)
):
    return _get_zone_or_404(db, zone_id)


@router.put("/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: int,
    data: ZoneIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    zone = _get_zone_or_404(db, zone_id)
    _check_code_not_taken(db, data.code, exclude_zone_id=zone_id)
    for key, value in data.model_dump().items():
        setattr(zone, key, value)
    db.add(AuditLog(user_id=admin.id, action="update_zone", target=zone.code))
    db.commit()
    db.refresh(zone)
    return zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    zone = _get_zone_or_404(db, zone_id)
    db.add(AuditLog(user_id=admin.id, action="delete_zone", target=zone.code))
    db.delete(zone)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "ลบไม่ได้ เพราะมีช่องจอดผูกกับโซนนี้อยู่")


@router.post("/{zone_id}/close", response_model=ZoneOut)
def close_zone(
    zone_id: int,
    data: ZoneCloseIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """ปิด/เปิดโซนชั่วคราว (Admin และ Operator ทำได้ ตาม SPEC ข้อ 7.2)"""
    zone = _get_zone_or_404(db, zone_id)
    zone.is_closed = data.is_closed
    zone.closed_note = data.closed_note
    action = "close_zone" if data.is_closed else "reopen_zone"
    db.add(AuditLog(user_id=user.id, action=action, target=zone.code))
    db.commit()
    db.refresh(zone)
    return zone


def _get_zone_or_404(db: Session, zone_id: int) -> Zone:
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบโซนนี้")
    return zone


def _check_code_not_taken(db: Session, code: str, exclude_zone_id: int | None = None) -> None:
    query = select(Zone).where(Zone.code == code)
    if exclude_zone_id is not None:
        query = query.where(Zone.id != exclude_zone_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"มีโซนรหัส '{code}' อยู่แล้ว")
