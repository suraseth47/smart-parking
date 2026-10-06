"""Layout editor: ดู/บันทึก draft, publish ช่องจอด (FR-24, FR-26)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_db
from core.models import AuditLog, Camera, LayoutStatus, Slot, SlotType, Zone
from web.camera_utils import build_camera_url
from web.deps import CurrentUser, require_admin, verify_csrf
from worker.camera_connection import check_camera_connection

router = APIRouter(prefix="/api/admin", tags=["layout"])


class SlotIn(BaseModel):
    id: int | None = None  # None = ช่องใหม่, มีค่า = แก้ไขช่องเดิม
    code: str
    zone_id: int
    type: SlotType = SlotType.NORMAL
    polygon: list[list[float]]  # normalized [[x,y], ...]
    threshold: float = 0.30
    is_active: bool = True


class SlotOut(BaseModel):
    id: int
    code: str
    camera_id: int
    zone_id: int
    type: SlotType
    polygon: list[list[float]]
    threshold: float
    is_active: bool
    layout_status: LayoutStatus

    model_config = {"from_attributes": True}


class SlotsSaveRequest(BaseModel):
    slots: list[SlotIn]


@router.get("/cameras/{camera_id}/slots", response_model=list[SlotOut])
def list_slots(
    camera_id: int,
    status_filter: LayoutStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    _get_camera_or_404(db, camera_id)
    query = select(Slot).where(Slot.camera_id == camera_id)
    if status_filter is not None:
        query = query.where(Slot.layout_status == status_filter)
    return db.scalars(query.order_by(Slot.code)).all()


@router.put("/cameras/{camera_id}/slots", response_model=list[SlotOut])
def save_draft_slots(
    camera_id: int,
    data: SlotsSaveRequest,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """บันทึกช่องจอดทั้งหมดของกล้องนี้เป็น draft แทนที่ชุดเดิมทั้งหมด (FR-24)

    หน้า editor ต้อง GET ช่องเดิมมาก่อนเสมอ แล้วส่งชุดเต็ม (เดิม+ที่แก้ไข+ที่เพิ่มใหม่)
    กลับมาที่นี่ — ช่องเดิมที่ไม่ได้ส่งกลับมาจะถือว่าถูกลบ
    """
    _get_camera_or_404(db, camera_id)
    _validate_zone_ids_exist(db, data.slots)

    keep_ids = {s.id for s in data.slots if s.id is not None}
    existing = db.scalars(select(Slot).where(Slot.camera_id == camera_id)).all()
    for slot in existing:
        if slot.id not in keep_ids:
            db.delete(slot)
    db.flush()

    saved: list[Slot] = []
    for item in data.slots:
        if item.id is not None:
            slot = db.get(Slot, item.id)
            if slot is None or slot.camera_id != camera_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ไม่พบช่อง id={item.id} ในกล้องนี้")
        else:
            slot = Slot(camera_id=camera_id)
            db.add(slot)

        slot.code = item.code
        slot.zone_id = item.zone_id
        slot.type = item.type
        slot.polygon = item.polygon
        slot.threshold = item.threshold
        slot.is_active = item.is_active
        slot.layout_status = LayoutStatus.DRAFT
        saved.append(slot)

    db.add(
        AuditLog(
            user_id=admin.id,
            action="save_draft_layout",
            target=f"camera:{camera_id}",
            detail={"slot_count": len(saved)},
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "มีรหัสช่องซ้ำกับช่องจอดอื่นในระบบ")

    for slot in saved:
        db.refresh(slot)
    return saved


@router.post("/cameras/{camera_id}/slots/publish")
def publish_slots(
    camera_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """ยืนยัน draft -> published และบันทึกภาพอ้างอิงของกล้อง (FR-26)"""
    camera = _get_camera_or_404(db, camera_id)
    slots = db.scalars(select(Slot).where(Slot.camera_id == camera_id)).all()

    reference_path = get_settings().data_dir / "snapshots" / f"camera_{camera_id}_reference.jpg"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    result = check_camera_connection(build_camera_url(camera), reference_path)
    if not result.ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพอ้างอิงไม่สำเร็จ: {result.message}")

    for slot in slots:
        slot.layout_status = LayoutStatus.PUBLISHED
    camera.reference_image_path = str(reference_path)

    db.add(
        AuditLog(
            user_id=admin.id,
            action="publish_layout",
            target=f"camera:{camera_id}",
            detail={"slot_count": len(slots)},
        )
    )
    db.commit()
    return {"ok": True, "published_count": len(slots)}


def _get_camera_or_404(db: Session, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera


def _validate_zone_ids_exist(db: Session, slots: list[SlotIn]) -> None:
    zone_ids = {s.zone_id for s in slots}
    if not zone_ids:
        return
    found = set(db.scalars(select(Zone.id).where(Zone.id.in_(zone_ids))).all())
    missing = zone_ids - found
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ไม่พบโซน id={sorted(missing)}")
