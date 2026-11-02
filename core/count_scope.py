"""ขอบเขตการนับช่องจอด — สถานที่/กล้องที่ "ไม่นับรวม" (เช่น กล้องทดสอบ ValidationTestCam)

ตั้งได้ที่ ตั้งค่าระบบ → การนับช่องจอด
- กล้องไม่นับรวม: ช่องของกล้องนี้ไม่ถูกนับในยอดว่าง/ยอดรวม หน้าสาธารณะ ภาพรวม รายงาน และสถิติ
  (กล้องยังตรวจจับตามปกติ ดูได้ที่หน้าสถานะสด / ทดสอบความแม่นยำได้)
- สถานที่ไม่นับรวม: ทุกกล้องของสถานที่นั้นไม่นับ + ไม่แสดงในหน้าสาธารณะ + ไม่รวมในยอดรวมทุกสถานที่
"""
from __future__ import annotations

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from core.models import Camera, Site, Slot


def uncounted_camera_ids(db: Session) -> set[int]:
    rows = db.execute(
        select(Camera.id).outerjoin(Site, Site.id == Camera.site_id).where(
            (Camera.counted.is_(False)) | (Site.counted.is_(False))
        )
    ).all()
    return {r[0] for r in rows}


def counted_slots(db: Session):
    """เงื่อนไข where สำหรับ query ช่องจอด: เฉพาะช่องของกล้องที่นับรวม"""
    ids = uncounted_camera_ids(db)
    return Slot.camera_id.notin_(ids) if ids else true()
