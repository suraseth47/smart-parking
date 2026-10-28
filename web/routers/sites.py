"""สถานที่จอดรถ (TOR 4.6): ภาพรวมทุกสถานที่จากจุดเดียว + เพิ่ม/แก้/ลบสถานที่ (Admin)"""
from __future__ import annotations

import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.counting import COUNTABLE_TYPES
from core.db import get_db
from core.models import (
    Alert, AuditLog, Camera, LayoutStatus, OccupancyState, Site, Slot, SlotState, User, Zone,
)
from core.sites import google_maps_directions_url
from web.deps import CurrentUser, get_current_user, require_admin, verify_csrf
from web.site_access import restrict

router = APIRouter(prefix="/api/admin/sites", tags=["sites"])

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


class SiteIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name_th: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    opening_hours: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    sort_order: int = 0
    is_public: bool = True


def _site_base(site: Site) -> dict:
    return {
        "id": site.id, "code": site.code, "name_th": site.name_th, "name_en": site.name_en,
        "address": site.address, "opening_hours": site.opening_hours,
        "latitude": site.latitude, "longitude": site.longitude,
        "sort_order": site.sort_order, "is_public": site.is_public,
        "maps_url": google_maps_directions_url(site.latitude, site.longitude),
    }


def site_overview(db: Session, sites: list[Site]) -> list[dict]:
    """สถานะของแต่ละสถานที่: กล้อง online/offline, ช่องว่าง/มีรถ/ไม่ทราบ, แจ้งเตือนค้าง"""
    site_ids = [s.id for s in sites]
    zones = db.scalars(select(Zone).where(Zone.site_id.in_(site_ids or [-1]))).all()
    zone_site = {z.id: z.site_id for z in zones}
    closed_zone_ids = {z.id for z in zones if z.is_closed}

    cameras = db.scalars(select(Camera).where(Camera.site_id.in_(site_ids or [-1]))).all()
    camera_site = {c.id: c.site_id for c in cameras}

    slot_rows = db.execute(
        select(Slot.zone_id, Slot.type, SlotState.state)
        .outerjoin(SlotState, SlotState.slot_id == Slot.id)
        .where(Slot.layout_status == LayoutStatus.PUBLISHED, Slot.is_active.is_(True), Slot.zone_id.in_(list(zone_site) or [-1]))
    ).all()

    open_alerts = db.scalars(select(Alert).where(Alert.resolved_at.is_(None))).all()
    alert_count: dict[int, int] = {}
    for alert in open_alerts:
        parts = alert.source.split(":")
        if len(parts) == 3 and parts[0] == "camera" and parts[1].isdigit():
            sid = camera_site.get(int(parts[1]))
            if sid is not None:
                alert_count[sid] = alert_count.get(sid, 0) + 1

    result = []
    for site in sites:
        site_cams = [c for c in cameras if c.site_id == site.id]
        cam_status = {"online": 0, "offline": 0, "moved": 0, "disabled": 0}
        for c in site_cams:
            key = "disabled" if not c.enabled else getattr(c.status, "value", str(c.status))
            cam_status[key] = cam_status.get(key, 0) + 1
        counts = {"capacity": 0, "free": 0, "occupied": 0, "unknown": 0, "reserved": 0, "closed_zones": 0,
                  "free_disabled": 0, "free_ev": 0}
        for zone_id, slot_type, state in slot_rows:
            if zone_site.get(zone_id) != site.id or zone_id in closed_zone_ids:
                continue
            if getattr(slot_type, "value", slot_type) not in COUNTABLE_TYPES:
                counts["reserved"] += 1
                continue
            counts["capacity"] += 1
            value = getattr(state, "value", state) if state else OccupancyState.UNKNOWN.value
            counts[value if value in ("free", "occupied") else "unknown"] += 1
            if value == "free" and getattr(slot_type, "value", slot_type) in ("disabled", "ev"):
                counts["free_" + getattr(slot_type, "value", slot_type)] += 1
        counts["closed_zones"] = sum(1 for z in zones if z.site_id == site.id and z.is_closed)
        frames = [c.last_frame_at for c in site_cams if c.enabled and c.last_frame_at]
        result.append({
            **_site_base(site),
            "zone_count": sum(1 for z in zones if z.site_id == site.id),
            "camera_count": len(site_cams),
            "cameras": cam_status,
            **counts,
            "occupancy_pct": round(counts["occupied"] * 100 / counts["capacity"], 1) if counts["capacity"] else None,
            "open_alerts": alert_count.get(site.id, 0),
            "updated_at": max(frames).isoformat() if frames else None,
        })
    return result


@router.get("")
def list_sites(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """สถานที่ที่ผู้ใช้ดูแล พร้อมสถานะสด (ใช้ทั้งหน้า "ภาพรวมทุกสถานที่" และตัวเลือกสถานที่ในฟอร์มต่างๆ)"""
    sites = db.scalars(restrict(select(Site), Site.id, user).order_by(Site.sort_order, Site.id)).all()
    return site_overview(db, list(sites))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_site(
    data: SiteIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    values = _clean(db, data)
    site = Site(**values)
    db.add(site)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_site", target=site.code, detail={"name": site.name_th}))
    db.commit()
    db.refresh(site)
    return site_overview(db, [site])[0]


@router.put("/{site_id}")
def update_site(
    site_id: int,
    data: SiteIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    site = _get_or_404(db, site_id)
    for key, value in _clean(db, data, exclude_id=site_id).items():
        setattr(site, key, value)
    db.add(AuditLog(user_id=admin.id, action="update_site", target=site.code, detail={"name": site.name_th}))
    db.commit()
    db.refresh(site)
    return site_overview(db, [site])[0]


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(
    site_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
) -> None:
    site = _get_or_404(db, site_id)
    zones = db.scalar(select(func.count()).select_from(Zone).where(Zone.site_id == site_id)) or 0
    cameras = db.scalar(select(func.count()).select_from(Camera).where(Camera.site_id == site_id)) or 0
    if zones or cameras:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"ลบไม่ได้ เพราะสถานที่นี้ยังมีโซน {zones} โซน และกล้อง {cameras} ตัว — ย้ายหรือลบออกก่อน",
        )
    # เอา id นี้ออกจากสิทธิ์ของผู้ใช้ที่ถูกจำกัดไว้ (ไม่ให้เหลือ id ค้าง)
    for user in db.scalars(select(User).where(User.site_ids.is_not(None))).all():
        if site_id in (user.site_ids or []):
            user.site_ids = [s for s in user.site_ids if s != site_id]
    db.add(AuditLog(user_id=admin.id, action="delete_site", target=site.code, detail={"name": site.name_th}))
    db.delete(site)
    db.commit()


def _clean(db: Session, data: SiteIn, exclude_id: int | None = None) -> dict:
    values = data.model_dump()
    values["code"] = data.code.strip().upper()
    if not CODE_RE.match(values["code"]):
        raise HTTPException(422, "รหัสสถานที่ใช้ได้เฉพาะ A-Z 0-9 _ - (ไม่เกิน 20 ตัว) เช่น CITYHALL, MKT1")
    for key in ("name_th", "name_en"):
        values[key] = values[key].strip()
        if not values[key]:
            raise HTTPException(422, "กรุณากรอกชื่อสถานที่ทั้งภาษาไทยและภาษาอังกฤษ")
    for key in ("address", "opening_hours"):
        values[key] = (values[key] or "").strip() or None
    if (values["latitude"] is None) != (values["longitude"] is None):
        raise HTTPException(422, "กรอกพิกัดให้ครบทั้งละติจูดและลองจิจูด (หรือเว้นว่างทั้งคู่)")
    query = select(Site).where(Site.code == values["code"])
    if exclude_id is not None:
        query = query.where(Site.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"มีสถานที่รหัส '{values['code']}' อยู่แล้ว")
    return values


def _get_or_404(db: Session, site_id: int) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบสถานที่นี้")
    return site

