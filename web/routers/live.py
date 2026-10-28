"""Live view: ภาพล่าสุด + สถานะ/score ทุกช่อง (FR-33)"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import Camera, LayoutStatus, Slot, SlotState
from web.deps import CurrentUser, require_permission
from web.site_access import ensure_camera, restrict

router = APIRouter(prefix="/api/admin/live", tags=["live"])


class LiveCameraPickerOut(BaseModel):
    id: int
    name: str
    status: str
    site_id: int | None = None


class LiveSlotOut(BaseModel):
    code: str
    type: str
    polygon: list[list[float]]
    state: str
    score: float | None
    updated_at: str | None


class LiveCameraOut(BaseModel):
    id: int
    name: str
    status: str
    last_frame_at: str | None


class LiveOut(BaseModel):
    camera: LiveCameraOut
    snapshot_url: str
    slots: list[LiveSlotOut]


@router.get("/cameras", response_model=list[LiveCameraPickerOut])
def list_live_cameras(db: Session = Depends(get_db), user: CurrentUser = Depends(require_permission("live"))):
    """รายชื่อกล้องแบบย่อ ใช้เป็นตัวเลือกในหน้า Live (Operator เข้าได้ ต่างจาก /cameras ที่ Admin เท่านั้น)
    เฉพาะกล้องของสถานที่ที่ผู้ใช้ดูแล"""
    query = restrict(select(Camera).where(Camera.enabled.is_(True)), Camera.site_id, user)
    cameras = db.scalars(query.order_by(Camera.name)).all()
    return [{"id": c.id, "name": c.name, "status": c.status.value, "site_id": c.site_id} for c in cameras]


@router.get("/{camera_id}", response_model=LiveOut)
def get_live(
    camera_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require_permission("live"))
):
    camera = ensure_camera(user, db.get(Camera, camera_id))

    rows = db.execute(
        select(Slot, SlotState)
        .outerjoin(SlotState, SlotState.slot_id == Slot.id)
        .where(
            Slot.camera_id == camera_id,
            Slot.layout_status == LayoutStatus.PUBLISHED,
            Slot.is_active.is_(True),
        )
        .order_by(Slot.code)
    ).all()

    slots = [
        {
            "code": slot.code,
            "type": slot.type.value,
            "polygon": slot.polygon,
            "state": state.state.value if state else "unknown",
            "score": state.score if state else None,
            "updated_at": state.updated_at.isoformat() if state and state.updated_at else None,
        }
        for slot, state in rows
    ]

    return {
        "camera": {
            "id": camera.id,
            "name": camera.name,
            "status": camera.status.value,
            "last_frame_at": camera.last_frame_at.isoformat() if camera.last_frame_at else None,
        },
        "snapshot_url": f"/api/admin/cameras/{camera.id}/snapshot",
        "slots": slots,
    }
