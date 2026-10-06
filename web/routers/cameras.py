"""จัดการกล้อง: CRUD + Test connection + snapshot (FR-21..23)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_db
from core.models import AuditLog, Camera, CameraBrand, CameraStream
from core.security import encrypt_camera_password
from web.camera_utils import build_camera_url
from web.deps import CurrentUser, get_current_user, require_admin, verify_csrf
from worker.camera_connection import check_camera_connection

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
    snapshot_path = _snapshot_path(camera_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    result = check_camera_connection(url, snapshot_path)
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
    snapshot_path = _snapshot_path(camera_id)
    if not snapshot_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ยังไม่มีภาพ snapshot กรุณากด Test connection ก่อน")
    return FileResponse(snapshot_path)


def _camera_fields(data: CameraIn) -> dict:
    fields = data.model_dump(exclude={"password"})
    fields["password_enc"] = encrypt_camera_password(data.password) if data.password else None
    return fields


def _get_camera_or_404(db: Session, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera


def _snapshot_path(camera_id: int):
    return get_settings().data_dir / "snapshots" / f"camera_{camera_id}.jpg"
