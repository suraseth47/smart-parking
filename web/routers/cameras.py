"""จัดการกล้อง: CRUD + Test connection + snapshot + Re-align (FR-21..23, FR-30 เฟส 3)"""
from __future__ import annotations

from datetime import datetime

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, Camera, CameraBrand, CameraStatus, CameraStream, LayoutStatus, Slot
from core.security import encrypt_camera_password
from core.camera_utils import build_camera_url, snapshot_path as get_snapshot_path
from web.deps import CurrentUser, get_current_user, require_admin, verify_csrf
from worker.camera_connection import check_camera_connection
from worker.capture import grab_frame
from worker.health import apply_transform_to_polygon, compute_camera_transform, resolve_alerts

router = APIRouter(prefix="/api/admin/cameras", tags=["cameras"])


class CameraIn(BaseModel):
    name: str
    brand: CameraBrand
    host: str
    port: int = 554
    channel: int = 1
    stream: CameraStream = CameraStream.MAIN
    rtsp_url_custom: str | None = None
    username: str | None = None
    password: str | None = None  # รับเป็น plaintext แล้วเข้ารหัสก่อนเก็บ (FR-23)
    enabled: bool = True
    detect_interval_s: int = 30
    conf_threshold: float = 0.35
    tiling_enabled: bool = False
    roi_polygon: list | None = None


class CameraOut(BaseModel):
    id: int
    name: str
    brand: CameraBrand
    host: str
    port: int
    channel: int
    stream: CameraStream
    rtsp_url_custom: str | None
    username: str | None
    enabled: bool
    detect_interval_s: int
    conf_threshold: float
    tiling_enabled: bool
    large_object_min_area: float | None = None
    roi_polygon: list | None
    status: str
    reference_image_path: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    return db.scalars(select(Camera)).all()


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(
    data: CameraIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    camera = Camera(**_camera_fields(data))
    db.add(camera)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_camera", target=camera.name))
    db.commit()
    db.refresh(camera)
    return camera


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(
    camera_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    return _get_camera_or_404(db, camera_id)


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    data: CameraIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    camera = _get_camera_or_404(db, camera_id)
    for key, value in _camera_fields(data).items():
        setattr(camera, key, value)
    db.add(AuditLog(user_id=admin.id, action="update_camera", target=camera.name))
    db.commit()
    db.refresh(camera)
    return camera


class DetectionSettingsIn(BaseModel):
    # None = ปิดโหมด "นับวัตถุขนาดใหญ่เป็นรถ"; ตัวเลข = ขนาดกรอบขั้นต่ำเป็นสัดส่วนพื้นที่ภาพ
    large_object_min_area: float | None = Field(default=None, ge=0.005, le=0.5)


@router.patch("/{camera_id}/detection", response_model=CameraOut)
def update_detection_settings(
    camera_id: int,
    data: DetectionSettingsIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """ตั้งค่าการตรวจจับรายกล้อง โดยไม่แตะข้อมูลเชื่อมต่อกล้อง (รหัสผ่านกล้องไม่หาย)"""
    camera = _get_camera_or_404(db, camera_id)
    camera.large_object_min_area = data.large_object_min_area
    db.add(
        AuditLog(
            user_id=admin.id,
            action="update_camera_detection",
            target=camera.name,
            detail={"large_object_min_area": data.large_object_min_area},
        )
    )
    db.commit()
    db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    camera = _get_camera_or_404(db, camera_id)
    db.add(AuditLog(user_id=admin.id, action="delete_camera", target=camera.name))
    db.delete(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "ลบไม่ได้ เพราะมีช่องจอดผูกกับกล้องนี้อยู่")


@router.post("/{camera_id}/test")
def test_camera_connection(
    camera_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    camera = _get_camera_or_404(db, camera_id)
    url = build_camera_url(camera)
    path = get_snapshot_path(camera_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    result = check_camera_connection(url, path)
    if not result.ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, result.message)
    return {
        "ok": True,
        "message": result.message,
        "snapshot_url": f"/api/admin/cameras/{camera.id}/snapshot",
    }


@router.get("/{camera_id}/snapshot")
def get_camera_snapshot(
    camera_id: int, db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)
):
    _get_camera_or_404(db, camera_id)
    path = get_snapshot_path(camera_id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ยังไม่มีภาพ snapshot กรุณากด Test connection ก่อน")
    return FileResponse(path)


class RealignSlotPreview(BaseModel):
    slot_id: int
    code: str
    old_polygon: list[list[float]]
    new_polygon: list[list[float]]


class RealignPreviewOut(BaseModel):
    transform_found: bool
    snapshot_url: str
    slots: list[RealignSlotPreview]


@router.post("/{camera_id}/realign/preview", response_model=RealignPreviewOut)
def preview_realign(
    camera_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    """คำนวณ homography จากกล้องที่ขยับ แล้ว preview กรอบที่จะขยับให้ (FR-30 เฟส 3) — ไม่บันทึกอะไรลง DB"""
    camera = _get_camera_or_404(db, camera_id)
    if not camera.reference_image_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "กล้องนี้ยังไม่มีภาพอ้างอิง (ต้อง publish layout ก่อน)")

    try:
        reference = grab_frame(camera.reference_image_path)
        current = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพไม่สำเร็จ: {exc}")

    transform = compute_camera_transform(reference, current)
    path = get_snapshot_path(camera_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    cv2.imencode(".jpg", current)[1].tofile(str(path))

    if transform is None:
        return RealignPreviewOut(
            transform_found=False, snapshot_url=f"/api/admin/cameras/{camera_id}/snapshot", slots=[]
        )

    frame_h, frame_w = current.shape[:2]
    slots = db.scalars(
        select(Slot).where(Slot.camera_id == camera_id, Slot.layout_status == LayoutStatus.PUBLISHED)
    ).all()
    previews = [
        RealignSlotPreview(
            slot_id=slot.id,
            code=slot.code,
            old_polygon=slot.polygon,
            new_polygon=apply_transform_to_polygon(slot.polygon, transform, frame_w, frame_h),
        )
        for slot in slots
    ]
    return RealignPreviewOut(
        transform_found=True, snapshot_url=f"/api/admin/cameras/{camera_id}/snapshot", slots=previews
    )


@router.post("/{camera_id}/realign/confirm")
def confirm_realign(
    camera_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """Admin ยืนยันผล Re-align -> ขยับช่องที่ publish แล้วจริง, คืนสถานะกล้อง, ตั้งภาพอ้างอิงใหม่ (FR-30 เฟส 3)"""
    camera = _get_camera_or_404(db, camera_id)
    if not camera.reference_image_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "กล้องนี้ยังไม่มีภาพอ้างอิง (ต้อง publish layout ก่อน)")

    try:
        reference = grab_frame(camera.reference_image_path)
        current = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพไม่สำเร็จ: {exc}")

    transform = compute_camera_transform(reference, current)
    if transform is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "คำนวณ transform ไม่ได้ (หาจุดสังเกตร่วมไม่พอ) ลองใหม่อีกครั้ง")

    frame_h, frame_w = current.shape[:2]
    slots = db.scalars(
        select(Slot).where(Slot.camera_id == camera_id, Slot.layout_status == LayoutStatus.PUBLISHED)
    ).all()
    for slot in slots:
        slot.polygon = apply_transform_to_polygon(slot.polygon, transform, frame_w, frame_h)

    reference_path = get_snapshot_path(camera_id).parent / f"camera_{camera_id}_reference.jpg"
    reference_path.parent.mkdir(parents=True, exist_ok=True)

    cv2.imencode(".jpg", current)[1].tofile(str(reference_path))
    camera.reference_image_path = str(reference_path)
    camera.status = CameraStatus.ONLINE
    camera.last_health_check_at = datetime.utcnow()
    resolve_alerts(db, f"camera:{camera.id}:moved")

    db.add(
        AuditLog(
            user_id=admin.id,
            action="realign_camera",
            target=f"camera:{camera.id}",
            detail={"slot_count": len(slots)},
        )
    )
    db.commit()
    return {"ok": True, "realigned_slot_count": len(slots)}


def _camera_fields(data: CameraIn) -> dict:
    fields = data.model_dump(exclude={"password"})
    fields["password_enc"] = encrypt_camera_password(data.password) if data.password else None
    return fields


def _get_camera_or_404(db: Session, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera
