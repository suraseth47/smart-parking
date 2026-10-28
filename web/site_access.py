"""ตรวจสิทธิ์รายสถานที่ (TOR 4.6) ที่ API — เจ้าหน้าที่เห็น/แก้ได้เฉพาะกล้อง โซน และช่องของสถานที่ที่ดูแล

ข้อมูลของสถานที่อื่นตอบเป็น 404 (ไม่บอกว่ามีอยู่) เหมือนไม่มีข้อมูลนั้นในระบบ
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models import Camera, Slot, Zone
from web.deps import CurrentUser


def restrict(query, column, user: CurrentUser):
    """เพิ่มเงื่อนไข WHERE column IN (สถานที่ของผู้ใช้) — ผู้ใช้ทุกสถานที่ไม่กรอง"""
    if user.site_ids is None:
        return query
    return query.where(column.in_(user.site_ids or [-1]))


def ensure_camera(user: CurrentUser, camera: Camera | None) -> Camera:
    if camera is None or not user.can_see_site(camera.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera


def ensure_zone(user: CurrentUser, zone: Zone | None) -> Zone:
    if zone is None or not user.can_see_site(zone.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบโซนนี้")
    return zone


def ensure_slot(db: Session, user: CurrentUser, slot: Slot | None) -> Slot:
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบช่องนี้")
    zone = db.get(Zone, slot.zone_id)
    if zone is None or not user.can_see_site(zone.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบช่องนี้")
    return slot
