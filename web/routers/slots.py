"""Layout editor: ดู/บันทึก draft, publish, preview ช่องจอด (FR-24..26)"""
from __future__ import annotations

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import PROJECT_ROOT, get_settings
from core.db import get_db
from core.models import AuditLog, Camera, LayoutStatus, Slot, SlotEvent, SlotState, SlotType, Zone
from core.camera_utils import build_camera_url, snapshot_path
from web.deps import CurrentUser, require_admin, verify_csrf
from worker.camera_connection import check_camera_connection
from worker.capture import grab_frame
from worker.detector import OnnxYoloxDetector
from worker.occupancy import compute_slot_score, is_occupied
from worker.vehicle_boxes import detect_vehicle_footprints

router = APIRouter(prefix="/api/admin", tags=["layout"])

_detector: OnnxYoloxDetector | None = None


def _get_detector() -> OnnxYoloxDetector:
    """โหลดโมเดล YOLOX ครั้งแรกที่ใช้แล้วเก็บไว้ใช้ซ้ำ (โหลดโมเดลช้า ไม่อยากโหลดทุก request)"""
    global _detector
    if _detector is None:
        _detector = OnnxYoloxDetector(PROJECT_ROOT / "models" / "yolox_s.onnx")
    return _detector


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


class SlotPreviewIn(BaseModel):
    code: str
    polygon: list[list[float]]
    threshold: float = 0.30


class SlotPreviewRequest(BaseModel):
    slots: list[SlotPreviewIn]


class SlotPreviewResult(BaseModel):
    code: str
    score: float
    state: str  # "free" | "occupied"


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
    removed_ids = [slot.id for slot in existing if slot.id not in keep_ids]
    if removed_ids:
        # ลบสถานะและประวัติของช่องที่ถูกลบก่อน ไม่งั้น foreign key ทำให้ลบช่องที่เคย publish ไม่ได้
        db.execute(delete(SlotEvent).where(SlotEvent.slot_id.in_(removed_ids)))
        db.execute(delete(SlotState).where(SlotState.slot_id.in_(removed_ids)))
        db.execute(delete(Slot).where(Slot.id.in_(removed_ids)))
        db.expire_all()
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
            detail={"slot_count": len(saved), "removed_count": len(removed_ids)},
        )
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "UNIQUE" in str(exc.orig).upper():
            raise HTTPException(status.HTTP_409_CONFLICT, "มีรหัสช่องซ้ำกับช่องจอดอื่นในระบบ")
        raise HTTPException(status.HTTP_409_CONFLICT, f"บันทึกไม่สำเร็จ: {exc.orig}")

    for slot in saved:
        db.refresh(slot)
    return saved


@router.post("/cameras/{camera_id}/slots/preview")
def preview_slots(
    camera_id: int,
    data: SlotPreviewRequest,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    """ดึงภาพปัจจุบันจริง ตรวจจับรถ แล้วคำนวณ score ซ้อนทับกรอบที่กำลังแก้ (FR-25)

    ไม่บันทึกอะไรลง DB — ใช้ดูก่อน publish เท่านั้น
    """
    camera = _get_camera_or_404(db, camera_id)

    try:
        frame = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพจากกล้องไม่สำเร็จ: {exc}")

    footprints = detect_vehicle_footprints(_get_detector(), frame, camera.large_object_min_area)

    results = []
    for slot in data.slots:
        score = compute_slot_score(slot.polygon, footprints)
        state = "occupied" if is_occupied(score, slot.threshold) else "free"
        results.append(SlotPreviewResult(code=slot.code, score=round(score, 3), state=state))

    path = snapshot_path(camera_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", frame)[1].tofile(str(path))

    return {
        "snapshot_url": f"/api/admin/cameras/{camera_id}/snapshot",
        "detected_vehicle_count": len(footprints),
        "results": results,
    }


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
