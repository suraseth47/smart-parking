"""เมนู "แสดงกล้องและช่องจอดจริง": ภาพกล้องสด คู่กับหน้าจอที่ประชาชนเห็น (2 จอในหน้าเดียว)

ใช้ตอนนำเสนองาน หรือให้ Admin เทียบว่าช่องที่ระบบบอกว่า "ว่าง" ว่างจริงไหม
- ภาพกล้องใช้ /api/admin/cctv/{id}/frame (หลังบ้านเท่านั้น — PDPA)
- ฝั่งประชาชนใช้ตัวเลขชุดเดียวกับ /api/public/summary แต่ตัดเหลือเฉพาะโซนที่กล้องนี้มองเห็น
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import Camera, LayoutStatus, Site, Slot, SlotState, Zone
from web.deps import CurrentUser, require_permission
from web.routers.live import public_preview
from web.site_access import ensure_camera

router = APIRouter(prefix="/api/admin/showcase", tags=["showcase"])

SHOWCASE_KEY = "showcase"
STYLES = ("grid", "ring")  # grid = ผังช่องสี่เหลี่ยม · ring = แบบหน้าประชาชน (วงแหวน + การ์ดโซน)


def load_showcase(db: Session) -> dict:
    """ค่าตั้งของเมนูนี้ (ตั้งค่าระบบ → ระบบและการแสดงผล)"""
    from core.models import Setting

    row = db.get(Setting, SHOWCASE_KEY)
    style = row.value.get("style") if row and isinstance(row.value, dict) else None
    return {"style": style if style in STYLES else "grid"}


@router.get("/{camera_id}")
def get_showcase(camera_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require_permission("cctv"))) -> dict:
    camera = ensure_camera(user, db.get(Camera, camera_id))
    rows = db.execute(
        select(Slot, SlotState, Zone.code)
        .outerjoin(SlotState, SlotState.slot_id == Slot.id)
        .join(Zone, Zone.id == Slot.zone_id)
        .where(Slot.camera_id == camera.id, Slot.layout_status == LayoutStatus.PUBLISHED, Slot.is_active.is_(True))
        .order_by(Slot.code)
    ).all()
    slots = [
        {"code": slot.code, "type": slot.type.value, "polygon": slot.polygon, "zone": zone_code,
         "state": state.state.value if state else "unknown"}
        for slot, state, zone_code in rows
    ]
    camera_zone_codes = {s["zone"] for s in slots}

    public = public_preview(db, camera)
    if public.get("shown"):
        # เอาแผนผังช่อง (ชุดเดียวกับหน้าสาธารณะ) เฉพาะโซนที่กล้องนี้มองเห็น
        from web.routers.public import build_summary  # import ภายใน กัน import วนกัน

        summary = build_summary(db, db.get(Site, camera.site_id), site_count=0)
        # ยอดแยกสถานะของทั้งสถานที่ (กล่อง ว่าง / มีรถ / สงวน / ไม่ทราบ ของแบบวงแหวน)
        counts = {"free": 0, "occupied": 0, "locked": 0, "unknown": 0}
        for z in summary["zones"]:
            for item in z["slots"] or []:
                key = item["state"] if item["state"] in counts else "unknown"
                counts[key] += 1
        public["counts"] = counts
        public["zones"] = [
            {"code": z["code"], "name": z["name_th"], "status": z["status"], "free": z["free"],
             "capacity": z["capacity"], "slots": z["slots"] or []}
            for z in summary["zones"] if z["code"] in camera_zone_codes
        ]
        public["site_updated_at"] = summary["updated_at"]
        public["stale"] = summary["stale"]

    return {
        "camera": {"id": camera.id, "name": camera.name, "status": camera.status.value,
                   "last_frame_at": camera.last_frame_at.isoformat() if camera.last_frame_at else None},
        "slots": slots,
        "public": public,
        "style": load_showcase(db)["style"],
        "server_time": datetime.utcnow().isoformat(),
    }
