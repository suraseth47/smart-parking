"""หน้ากล้องวงจรปิด (หลังบ้านเท่านั้น): ภาพนิ่งจากกล้องอัปเดตทุก ~1 วินาที แบ่งจอ 1/4/8

ภาพมีใบหน้า/ทะเบียนรถ (ข้อมูลส่วนบุคคลตาม PDPA) จึงต้อง login ก่อนเสมอ
และห้ามนำ endpoint นี้ไปใช้ในหน้าสาธารณะ
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.camera_utils import build_camera_url, snapshot_path
from core.db import get_db
from core.models import Camera
from web.cctv_stream import live_frames, prefer_substream
from web.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/api/admin/cctv", tags=["cctv"])

NO_STORE = {"Cache-Control": "no-store"}


class CctvCameraOut(BaseModel):
    id: int
    name: str
    status: str


@router.get("/cameras", response_model=list[CctvCameraOut])
def list_cctv_cameras(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    cameras = db.scalars(select(Camera).where(Camera.enabled.is_(True)).order_by(Camera.id)).all()
    return [{"id": c.id, "name": c.name, "status": c.status.value} for c in cameras]


@router.get("/{camera_id}/frame")
def get_cctv_frame(camera_id: int, db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    """ภาพล่าสุดของกล้อง (JPEG) — ถ้าดึงภาพสดไม่ได้จะใช้ภาพล่าสุดที่ worker เก็บไว้แทน"""
    camera = db.get(Camera, camera_id)
    if camera is None or not camera.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

    try:
        url = prefer_substream(build_camera_url(camera))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    jpeg, frame_at, error = live_frames.get_frame(camera_id, url)
    if jpeg is not None:
        headers = dict(NO_STORE, **{"X-Frame-Source": "live"})
        if frame_at is not None:
            headers["X-Frame-Time"] = frame_at.isoformat()
        return Response(content=jpeg, media_type="image/jpeg", headers=headers)

    fallback = snapshot_path(camera_id)
    if fallback.exists():
        return FileResponse(fallback, media_type="image/jpeg", headers=dict(NO_STORE, **{"X-Frame-Source": "snapshot"}))

    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error or "ยังไม่มีภาพจากกล้องนี้")
