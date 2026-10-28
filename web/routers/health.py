"""Health dashboard + alerts ในหลังบ้าน (FR-31, FR-32)"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import psutil
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_db
from core.models import Alert, AuditLog, Camera
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
    kind: str = "other"  # connection | moved | other — ใช้แสดงไอคอน/ชื่อประเภท
    camera_id: int | None = None
    message: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class SystemWarningOut(BaseModel):
    """ปัญหาที่คำนวณจากสภาพระบบตอนนี้ (ไม่ได้เก็บเป็น alert) หายเองเมื่อแก้แล้ว"""
    key: str
    level: str
    message: str


class AlertSummaryOut(BaseModel):
    open_count: int
    error_count: int
    system: list[SystemWarningOut]


WORKER_STALE_AFTER = timedelta(minutes=5)
DISK_WARN_PERCENT = 90.0


def _visible_alerts(db: Session, user: CurrentUser, alerts: list[Alert]) -> list[Alert]:
    """แจ้งเตือนของกล้องนอกสถานที่ที่ผู้ใช้ดูแลจะไม่แสดง (แจ้งเตือนระดับระบบแสดงทุกคน)"""
    if user.site_ids is None:
        return alerts
    camera_site = dict(db.execute(select(Camera.id, Camera.site_id)).all())
    visible = []
    for alert in alerts:
        camera_id = _alert_out(alert)["camera_id"]
        if camera_id is None or user.can_see_site(camera_site.get(camera_id)):
            visible.append(alert)
    return visible


def _alert_out(alert: Alert) -> dict:
    parts = alert.source.split(":")
    camera_id = int(parts[1]) if len(parts) == 3 and parts[0] == "camera" and parts[1].isdigit() else None
    kind = parts[2] if camera_id is not None and parts[2] in ("connection", "moved") else "other"
    data = AlertOut.model_validate(alert).model_dump()
    data.update(level=getattr(alert.level, "value", alert.level), kind=kind, camera_id=camera_id)
    return data


def system_warnings(cameras: list[Camera], now: datetime, disk_percent: float | None) -> list[dict]:
    """ตรวจ "ระบบทำงานผิดปกติ" ที่ worker แจ้งเองไม่ได้ (เช่น worker หยุดทำงานไปเลย) — pure function"""
    warnings = []
    enabled = [c for c in cameras if c.enabled]
    frames = [c.last_frame_at for c in enabled if c.last_frame_at is not None]
    if enabled and frames and now - max(frames) > WORKER_STALE_AFTER:
        minutes = int((now - max(frames)).total_seconds() // 60)
        warnings.append({
            "key": "worker_stale", "level": "error",
            "message": f"ระบบประมวลผล AI ไม่ได้อัปเดตมา {minutes} นาที (worker อาจหยุดทำงาน) — หน้าสาธารณะจะแจ้งว่าข้อมูลไม่เป็นปัจจุบัน",
        })
    if disk_percent is not None and disk_percent >= DISK_WARN_PERCENT:
        warnings.append({
            "key": "disk_full", "level": "warning",
            "message": f"พื้นที่ดิสก์เครื่องแม่ข่ายใช้ไป {disk_percent:.0f}% ควรลบไฟล์เก่าหรือขยายพื้นที่",
        })
    return warnings


@router.get("/health", response_model=HealthOut)
def get_health(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    cameras = [c for c in db.scalars(select(Camera)).all() if user.can_see_site(c.site_id)]
    return {"cameras": cameras, "server": _get_server_stats()}


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    include_resolved: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = select(Alert).order_by(Alert.created_at.desc())
    if not include_resolved:
        query = query.where(Alert.resolved_at.is_(None))
    else:
        query = query.where(Alert.created_at >= datetime.utcnow() - timedelta(days=30)).limit(500)
    return [_alert_out(a) for a in _visible_alerts(db, user, db.scalars(query).all())]


@router.get("/alerts/summary", response_model=AlertSummaryOut)
def alerts_summary(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """ตัวเลขสำหรับกระดิ่งแจ้งเตือนที่หัวเว็บ (เรียกทุก 1 นาที จึงไม่วัด CPU ที่ใช้เวลานาน)"""
    open_alerts = _visible_alerts(db, user, db.scalars(select(Alert).where(Alert.resolved_at.is_(None))).all())
    try:
        disk = shutil.disk_usage(get_settings().data_dir)
        disk_percent = disk.used / disk.total * 100
    except OSError:
        disk_percent = None
    system = system_warnings(db.scalars(select(Camera)).all(), datetime.utcnow(), disk_percent)
    return {
        "open_count": len(open_alerts) + len(system),
        "error_count": sum(1 for a in open_alerts if getattr(a.level, "value", a.level) == "error")
        + sum(1 for w in system if w["level"] == "error"),
        "system": system,
    }


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("alerts", "override", "cameras")),
    _csrf: None = Depends(verify_csrf),
):
    alert = db.get(Alert, alert_id)
    if alert is not None and not _visible_alerts(db, user, [alert]):
        alert = None
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ alert นี้")
    if alert.resolved_at is None:
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by = user.id
        db.add(AuditLog(user_id=user.id, action="resolve_alert", target=alert.source, detail={"message": alert.message}))
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
