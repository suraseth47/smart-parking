"""จัดการกล้อง: CRUD + Test connection + snapshot + Re-align (FR-21..23, FR-30 เฟส 3)"""
from __future__ import annotations

from datetime import datetime

import base64
import tempfile
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import get_db
from core.camera_state import mark_camera_slots_unknown
from core.models import Alert, AuditLog, Camera, CameraBrand, CameraStatus, CameraStream, LayoutStatus, Site, Slot
from core.rtsp import build_rtsp_url
from core.security import decrypt_camera_password, encrypt_camera_password
from core.camera_utils import build_camera_url, snapshot_path as get_snapshot_path
from web.deps import CurrentUser, require_admin, require_permission, verify_csrf
from web.site_access import ensure_camera
from worker.camera_connection import check_camera_connection
from worker.capture import grab_frame
from worker.health import apply_transform_to_polygon, compute_camera_transform, resolve_alerts

router = APIRouter(prefix="/api/admin/cameras", tags=["cameras"])


class CameraIn(BaseModel):
    site_id: int | None = None  # ว่างได้เฉพาะตอนระบบมีสถานที่เดียว
    name: str = Field(min_length=1, max_length=100)
    brand: CameraBrand
    host: str = Field(default="", max_length=100)
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1, le=256)
    stream: CameraStream = CameraStream.MAIN
    rtsp_url_custom: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=100)
    # รับเป็น plaintext แล้วเข้ารหัสก่อนเก็บ (FR-23) — ตอนแก้ไข: ว่าง = ใช้รหัสเดิม
    password: str | None = Field(default=None, max_length=100)
    clear_password: bool = False
    enabled: bool = True
    detect_interval_s: int = Field(default=30, ge=5, le=3600)
    conf_threshold: float = Field(default=0.35, ge=0.05, le=0.95)
    tiling_enabled: bool = False
    roi_polygon: list | None = None


class CameraTestIn(CameraIn):
    camera_id: int | None = None  # ทดสอบตอนแก้ไขกล้องเดิม: รหัสผ่านว่าง = ใช้รหัสที่บันทึกไว้


class CameraOut(BaseModel):
    id: int
    site_id: int | None = None
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
    roi_auto_margin: float | None = None
    roi_polygon: list | None
    status: str
    reference_image_path: str | None
    last_frame_at: datetime | None = None
    last_error: str | None = None
    has_password: bool = False
    slot_count: int = 0

    model_config = {"from_attributes": True}


def _camera_out(db: Session, camera: Camera) -> dict:
    """ข้อมูลกล้องที่ส่งให้หน้าเว็บ — ไม่ส่งรหัสผ่าน (ส่งแค่ว่ามีบันทึกไว้หรือไม่)"""
    data = CameraOut.model_validate(camera).model_dump()
    data["status"] = camera.status.value if hasattr(camera.status, "value") else str(camera.status)
    data["has_password"] = bool(camera.password_enc)
    data["slot_count"] = db.scalar(select(func.count()).select_from(Slot).where(Slot.camera_id == camera.id)) or 0
    return data


@router.get("", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    return [_camera_out(db, c) for c in db.scalars(select(Camera).order_by(Camera.id)).all()]


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(
    data: CameraIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    fields = _camera_fields(db, data)
    fields["password_enc"] = encrypt_camera_password(data.password) if data.password else None
    if not data.enabled:
        fields["status"] = CameraStatus.DISABLED
    camera = Camera(**fields)
    db.add(camera)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_camera", target=camera.name))
    db.commit()
    db.refresh(camera)
    return _camera_out(db, camera)


@router.post("/test-config")
def test_camera_config(
    data: CameraTestIn,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """ทดสอบการเชื่อมต่อจากค่าในฟอร์ม ก่อนกดบันทึก (TOR 4.4) — คืนภาพตัวอย่างย่อขนาดเพื่อยืนยันว่าถูกกล้อง"""
    password = data.password or ""
    if not password and data.camera_id is not None and not data.clear_password:
        existing = _get_camera_or_404(db, data.camera_id)
        password = decrypt_camera_password(existing.password_enc) if existing.password_enc else ""
    if data.brand != CameraBrand.CUSTOM and not data.host.strip():
        raise HTTPException(422, "กรุณากรอก IP กล้อง")
    try:
        url = build_rtsp_url(
            brand=data.brand, host=data.host.strip(), port=data.port, channel=data.channel, stream=data.stream,
            username=data.username or "", password=password, rtsp_url_custom=(data.rtsp_url_custom or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "test.jpg"
        result = check_camera_connection(url, out)
        if not result.ok:
            return {"ok": False, "message": result.message}
        image = cv2.imread(str(out))
    if image is None:
        return {"ok": False, "message": "เชื่อมต่อได้ แต่อ่านภาพจากกล้องไม่ได้"}
    height, width = image.shape[:2]
    scale = min(1.0, 640 / width)
    preview = cv2.resize(image, (int(width * scale), int(height * scale))) if scale < 1 else image
    jpg = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()
    return {
        "ok": True,
        "message": f"เชื่อมต่อสำเร็จ · ภาพ {width}×{height}",
        "width": width,
        "height": height,
        "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(),
    }


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(
    camera_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)
):
    return _camera_out(db, _get_camera_or_404(db, camera_id))


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    data: CameraIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    camera = _get_camera_or_404(db, camera_id)
    was_enabled = camera.enabled
    fields = _camera_fields(db, data)
    if fields["site_id"] != camera.site_id and db.scalar(select(func.count()).select_from(Slot).where(Slot.camera_id == camera.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "ย้ายกล้องไปสถานที่อื่นไม่ได้ เพราะมีช่องจอดของสถานที่เดิมอยู่ — ลบช่องจอดของกล้องก่อน")
    if "roi_polygon" not in data.model_fields_set:
        fields.pop("roi_polygon")  # หน้าแก้ไขกล้องไม่ได้ส่ง ROI มา = คงค่าเดิม
    for key, value in fields.items():
        setattr(camera, key, value)
    # รหัสผ่าน: กรอกใหม่ = เปลี่ยน, ติ๊กล้าง = ลบ, ว่าง = คงเดิม (ไม่ต้องพิมพ์รหัสกล้องใหม่ทุกครั้งที่แก้ชื่อ)
    if data.password:
        camera.password_enc = encrypt_camera_password(data.password)
    elif data.clear_password:
        camera.password_enc = None
    changed = sorted(k for k in data.model_fields_set if k not in ("password", "clear_password", "roi_polygon"))
    if data.password or data.clear_password:
        changed.append("password")
    _apply_enabled(db, camera, was_enabled)
    db.add(AuditLog(user_id=admin.id, action="update_camera", target=camera.name, detail={"fields": changed}))
    db.commit()
    db.refresh(camera)
    return _camera_out(db, camera)


class CameraEnabledIn(BaseModel):
    enabled: bool


@router.patch("/{camera_id}/enabled", response_model=CameraOut)
def set_camera_enabled(
    camera_id: int,
    data: CameraEnabledIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """เปิด/ปิดใช้งานกล้อง (TOR 4.4) โดยไม่ต้องลบกล้องและช่องจอดที่วาดไว้"""
    camera = _get_camera_or_404(db, camera_id)
    was_enabled = camera.enabled
    camera.enabled = data.enabled
    _apply_enabled(db, camera, was_enabled)
    db.add(AuditLog(user_id=admin.id, action="enable_camera" if data.enabled else "disable_camera", target=camera.name))
    db.commit()
    db.refresh(camera)
    return _camera_out(db, camera)


def _apply_enabled(db: Session, camera: Camera, was_enabled: bool) -> None:
    """ผลข้างเคียงของการเปิด/ปิดกล้อง"""
    if was_enabled and not camera.enabled:
        # worker จะข้ามกล้องนี้ -> ช่องต้องเป็น "ไม่ทราบ" ไม่ใช่ค้างค่าเดิม และปิด alert ค้างของกล้อง
        camera.status = CameraStatus.DISABLED
        mark_camera_slots_unknown(db, camera)
        for source in (f"camera:{camera.id}:connection", f"camera:{camera.id}:moved"):
            resolve_alerts(db, source)
    elif camera.enabled and not was_enabled:
        camera.status = CameraStatus.OFFLINE  # รอ worker ดึงภาพรอบแรก แล้วจะเปลี่ยนเป็น online เอง
        camera.last_frame_at = None  # ให้ worker ประมวลผลกล้องนี้ทันทีในรอบถัดไป


class DetectionSettingsIn(BaseModel):
    # ส่งมาเฉพาะค่าที่ต้องการเปลี่ยน (ค่าที่ไม่ได้ส่งจะคงเดิม) — null = ปิดโหมดนั้น
    # large_object_min_area: ขนาดกรอบขั้นต่ำของ "นับวัตถุขนาดใหญ่เป็นรถ" (สัดส่วนพื้นที่ภาพ)
    large_object_min_area: float | None = Field(default=None, ge=0.005, le=0.5)
    # roi_auto_margin: ขอบเผื่อรอบช่องจอดของ ROI อัตโนมัติ (สัดส่วนของภาพ, FR-4)
    roi_auto_margin: float | None = Field(default=None, ge=0.0, le=0.5)


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
    changes = data.model_dump(include=data.model_fields_set)
    for key, value in changes.items():
        setattr(camera, key, value)
    db.add(AuditLog(user_id=admin.id, action="update_camera_detection", target=camera.name, detail=changes))
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
    slot_count = db.scalar(select(func.count()).select_from(Slot).where(Slot.camera_id == camera.id)) or 0
    if slot_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"ลบไม่ได้ เพราะกล้องนี้มีช่องจอด {slot_count} ช่อง — ใช้ \"ปิดใช้งาน\" แทน หรือลบช่องจอดของกล้องก่อน",
        )
    for alert in db.scalars(select(Alert).where(Alert.source.like(f"camera:{camera.id}:%"))).all():
        db.delete(alert)
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
    camera_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require_permission("live", "cameras"))
):
    ensure_camera(user, db.get(Camera, camera_id))
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


def _resolve_site_id(db: Session, site_id: int | None) -> int:
    if site_id is None:
        site_ids = db.scalars(select(Site.id)).all()
        if len(site_ids) != 1:
            raise HTTPException(422, "กรุณาเลือกสถานที่ของกล้องนี้")
        return site_ids[0]
    if db.get(Site, site_id) is None:
        raise HTTPException(422, "ไม่พบสถานที่ที่เลือก")
    return site_id


def _camera_fields(db: Session, data: CameraIn) -> dict:
    """ค่าที่บันทึกลงตาราง cameras (ไม่รวมรหัสผ่าน ซึ่งจัดการแยกในแต่ละ endpoint)"""
    if data.brand != CameraBrand.CUSTOM and not data.host.strip():
        raise HTTPException(422, "กรุณากรอก IP กล้อง")
    if data.brand == CameraBrand.CUSTOM and not (data.rtsp_url_custom or "").strip():
        raise HTTPException(422, "กล้องแบบกำหนดเองต้องกรอก RTSP URL")
    fields = data.model_dump(exclude={"password", "clear_password"})
    fields["site_id"] = _resolve_site_id(db, data.site_id)
    fields["name"] = data.name.strip()
    fields["host"] = data.host.strip()
    fields["rtsp_url_custom"] = (data.rtsp_url_custom or "").strip() or None
    fields["username"] = (data.username or "").strip() or None
    return fields


def _get_camera_or_404(db: Session, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera
