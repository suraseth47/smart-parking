"""สถานะช่องจอดตามสถานะกล้อง — ใช้ร่วมกันระหว่าง worker และหน้าจัดการกล้อง"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Camera, LayoutStatus, OccupancyState, Slot, SlotEvent, SlotState


def mark_camera_slots_unknown(db: Session, camera: Camera) -> None:
    """ดึงภาพไม่ได้ / กล้องถูกขยับ / กล้องถูกปิดใช้งาน -> ช่องที่ publish แล้วของกล้องนี้เป็น unknown (FR-9)

    สำคัญตอนปิดใช้งานกล้อง: worker จะข้ามกล้องนั้น ถ้าไม่ทำแบบนี้ สถานะช่องจะค้างค่าเก่า
    แล้วหน้าสาธารณะจะแสดงช่องว่าง/ไม่ว่าง ที่ไม่ใช่ความจริง
    """
    slots = db.scalars(
        select(Slot).where(Slot.camera_id == camera.id, Slot.layout_status == LayoutStatus.PUBLISHED)
    ).all()
    now = datetime.utcnow()
    for slot in slots:
        state_row = db.get(SlotState, slot.id)
        if state_row is None:
            state_row = SlotState(slot_id=slot.id, raw_history=[])
            db.add(state_row)

        if state_row.state != OccupancyState.UNKNOWN:
            db.add(
                SlotEvent(
                    slot_id=slot.id,
                    from_state=state_row.state or OccupancyState.UNKNOWN,
                    to_state=OccupancyState.UNKNOWN,
                    ts=now,
                )
            )
            state_row.since = now

        state_row.state = OccupancyState.UNKNOWN
        state_row.raw_history = []
        state_row.updated_at = now
