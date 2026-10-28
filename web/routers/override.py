"""Override: บังคับสถานะช่องชั่วคราว (FR-34) — Admin และ Operator ทำได้ทั้งคู่"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, LayoutStatus, OccupancyState, Slot, SlotEvent, SlotState, Zone
from web.site_access import ensure_slot, restrict
from web.deps import CurrentUser, require_permission, verify_csrf

router = APIRouter(prefix="/api/admin/slots", tags=["override"])

OVERRIDABLE_STATES = {"free", "occupied"}


class SlotPickerOut(BaseModel):
    id: int
    code: str
    zone_id: int
    zone_code: str
    camera_id: int
    type: str
    state: str
    override_state: str | None
    override_until: datetime | None
    override_note: str | None


class OverrideIn(BaseModel):
    state: str  # "free" | "occupied"
    note: str | None = None
    until: datetime | None = None


@router.get("", response_model=list[SlotPickerOut])
def list_slots_for_override(
    zone_id: int | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("override")),
):
    """รายการช่อง (ข้ามกล้อง/โซน) สำหรับเลือกทำ override — กรองตามโซนได้ (FR-34 'ทั้งโซน')
    เฉพาะช่องของสถานที่ที่ผู้ใช้ดูแล"""
    query = (
        select(Slot, SlotState, Zone.code)
        .join(Zone, Zone.id == Slot.zone_id)
        .outerjoin(SlotState, SlotState.slot_id == Slot.id)
        .where(Slot.layout_status == LayoutStatus.PUBLISHED, Slot.is_active.is_(True))
    )
    if zone_id is not None:
        query = query.where(Slot.zone_id == zone_id)
    query = restrict(query, Zone.site_id, user)
    rows = db.execute(query.order_by(Zone.code, Slot.code)).all()

    return [
        {
            "id": slot.id,
            "code": slot.code,
            "zone_id": slot.zone_id,
            "zone_code": zone_code,
            "camera_id": slot.camera_id,
            "type": slot.type.value,
            "state": state.state.value if state else "unknown",
            "override_state": state.override_state.value if state and state.override_state else None,
            "override_until": state.override_until if state else None,
            "override_note": state.override_note if state else None,
        }
        for slot, state, zone_code in rows
    ]


@router.post("/{slot_id}/override")
def set_override(
    slot_id: int,
    data: OverrideIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("override")),
    _csrf: None = Depends(verify_csrf),
):
    if data.state not in OVERRIDABLE_STATES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state ต้องเป็น free หรือ occupied เท่านั้น")

    slot = ensure_slot(db, user, db.get(Slot, slot_id))

    now = datetime.utcnow()
    state_row = db.get(SlotState, slot_id)
    if state_row is None:
        state_row = SlotState(slot_id=slot_id, state=OccupancyState.UNKNOWN, raw_history=[])
        db.add(state_row)

    previous_state = state_row.state or OccupancyState.UNKNOWN
    new_state = OccupancyState(data.state)

    state_row.override_state = new_state
    state_row.override_until = data.until
    state_row.override_by = user.id
    state_row.override_note = data.note

    if new_state != previous_state:
        db.add(SlotEvent(slot_id=slot_id, from_state=previous_state, to_state=new_state, ts=now))
        state_row.since = now
    state_row.state = new_state
    state_row.updated_at = now

    db.add(
        AuditLog(
            user_id=user.id,
            action="override_slot",
            target=slot.code,
            detail={"state": data.state, "note": data.note, "until": data.until.isoformat() if data.until else None},
        )
    )
    db.commit()
    return {"ok": True}


@router.delete("/{slot_id}/override")
def clear_override(
    slot_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("override")),
    _csrf: None = Depends(verify_csrf),
):
    slot = ensure_slot(db, user, db.get(Slot, slot_id))

    state_row = db.get(SlotState, slot_id)
    if state_row is None or state_row.override_state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ช่องนี้ไม่มี override อยู่")

    state_row.override_state = None
    state_row.override_until = None
    state_row.override_by = None
    state_row.override_note = None
    state_row.updated_at = datetime.utcnow()

    db.add(AuditLog(user_id=user.id, action="cancel_override_slot", target=slot.code))
    db.commit()
    return {"ok": True}
