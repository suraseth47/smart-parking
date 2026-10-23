"""Health dashboard + alerts ในหลังบ้าน (FR-31, FR-32)"""
from __future__ import annotations

import shutil
from datetime import datetime

import psutil
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_db
from core.models import Alert, Camera
from web.deps import CurrentUser, get_current_user, require_permission, verify_csrf

router = APIRouter(prefix="/api/admin", tags=["health"])


class CameraHealthOut(BaseModel):
    id: int
    name: str
    status: str
    last_frame_at: datetime | None
    last_health_check_at: datetime | None
    last_infer_ms: float | None
    last_error: str | None

    model_config = {"from_attributes": True}


class ServerStatsOut(BaseModel):
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    temperature_c: float | None


class HealthOut(BaseModel):
    cameras: list[CameraHealthOut]
    server: ServerStatsOut


class AlertOut(BaseModel):
    id: int
    level: str
    source: str
    message: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("/health", response_model=HealthOut)
def get_health(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    cameras = db.scalars(select(Camera)).all()
    return {"cameras": cameras, "server": _get_server_stats()}


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    include_resolved: bool = False,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    query = select(Alert).order_by(Alert.created_at.desc())
    if not include_resolved:
        query = query.where(Alert.resolved_at.is_(None))
    return db.scalars(query).all()


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_permission("override", "cameras")),
    _csrf: None = Depends(verify_csrf),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ alert นี้")
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


def _get_server_stats() -> dict:
    disk = shutil.disk_usage(get_settings().data_dir)
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "temperature_c": _read_temperature(),
    }


def _read_temperature() -> float | None:
    """อ่านอุณหภูมิ CPU ถ้าเครื่องรองรับ (ส่วนใหญ่ใช้ได้แค่บน Linux) ตาม FR-31 'ถ้าอ่านได้'"""
    sensors_fn = getattr(psutil, "sensors_temperatures", None)
    if sensors_fn is None:
        return None
    try:
        sensors = sensors_fn()
    except Exception:
        return None
    for readings in sensors.values():
        if readings:
            return readings[0].current
    return None
