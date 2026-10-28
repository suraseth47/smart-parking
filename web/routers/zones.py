"""จัดการโซน: CRUD + ปิด/เปิดโซนชั่วคราว (FR-35) + Coverage report (FR-27)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, LayoutStatus, Site, Slot, Zone
from web.deps import CurrentUser, get_current_user, require_admin, require_permission, verify_csrf
from web.site_access import ensure_zone, restrict

router = APIRouter(prefix="/api/admin/zones", tags=["zones"])


class ZoneIn(BaseModel):
    site_id: int | None = None  # ว่างได้เฉพาะตอนระบบมีสถานที่เดียว (ใช้สถานที่นั้นอัตโนมัติ)
    code: str = Field(min_length=1, max_length=20)
    name_th: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    floor: str | None = Field(default=None, max_length=20)
    sort_order: int = 0
    expected_slots: int = Field(default=0, ge=0, le=100000)
    is_public: bool = True


class ZoneOut(BaseModel):
    id: int
    site_id: int | None = None
    code: str
    name_th: str
    name_en: str
    floor: str | None
    sort_order: int
    expected_slots: int
    is_public: bool
    is_closed: bool
    closed_note: str | None

    model_config = {"from_attributes": True}


class ZoneCloseIn(BaseModel):
    is_closed: bool
    closed_note: str | None = Field(default=None, max_length=255)  # ข้อความแจ้งประชาชนบนหน้าสาธารณะ


@router.get("", response_model=list[ZoneOut])
def list_zones(
    site_id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """โซนของสถานที่ที่ผู้ใช้ดูแล (กรองสถานที่เดียวได้ด้วย ?site_id=)"""
    query = restrict(select(Zone), Zone.site_id, user)
    if site_id is not None:
        query = query.where(Zone.site_id == site_id)
    return db.scalars(query.order_by(Zone.site_id, Zone.sort_order, Zone.code)).all()


@router.post("", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
def create_zone(
    data: ZoneIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    values = _clean_zone(db, data)
    _check_code_not_taken(db, values["code"], values["site_id"])
    zone = Zone(**values)
    db.add(zone)
    db.flush()
    db.add(AuditLog(user_id=admin.id, action="create_zone", target=zone.code))
    db.commit()
    db.refresh(zone)
    return zone


@router.get("/overview")
def zones_overview(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """จำนวนช่องที่วาด/Publish แล้วของทุกโซน (ใช้ในหน้าจัดการโซน) — เรียกครั้งเดียวแทนการเรียกรายโซน"""
    query = select(Slot.zone_id, Slot.layout_status, func.count()).join(Zone, Zone.id == Slot.zone_id)
    rows = db.execute(restrict(query, Zone.site_id, user).group_by(Slot.zone_id, Slot.layout_status)).all()
    counts: dict[int, dict[str, int]] = {}
    for zone_id, layout_status, n in rows:
        bucket = counts.setdefault(zone_id, {"drawn": 0, "published": 0})
        bucket["drawn"] += n
        if layout_status == LayoutStatus.PUBLISHED:
            bucket["published"] += n
    return [{"zone_id": zid, "drawn_slots": c["drawn"], "published_slots": c["published"]} for zid, c in counts.items()]


@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(
    zone_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    return ensure_zone(user, db.get(Zone, zone_id))


@router.get("/{zone_id}/coverage")
def get_zone_coverage(
    zone_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """เทียบจำนวนช่องที่วาดแล้วกับ 'จำนวนช่องจริง' ที่ Admin กรอกไว้ (FR-27)"""
    zone = ensure_zone(user, db.get(Zone, zone_id))

    drawn_slots = db.scalar(
        select(func.count()).select_from(Slot).where(Slot.zone_id == zone_id)
    )
    published_slots = db.scalar(
        select(func.count())
        .select_from(Slot)
        .where(Slot.zone_id == zone_id, Slot.layout_status == LayoutStatus.PUBLISHED)
    )
    coverage_pct = (
        round(drawn_slots / zone.expected_slots * 100, 1) if zone.expected_slots > 0 else None
    )

    return {
        "zone_id": zone.id,
        "code": zone.code,
        "expected_slots": zone.expected_slots,
        "drawn_slots": drawn_slots,
        "published_slots": published_slots,
        "coverage_pct": coverage_pct,
    }


@router.put("/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: int,
    data: ZoneIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    zone = _get_zone_or_404(db, zone_id)
    values = _clean_zone(db, data)
    _check_code_not_taken(db, values["code"], values["site_id"], exclude_zone_id=zone_id)
    if values["site_id"] != zone.site_id and db.scalar(select(func.count()).select_from(Slot).where(Slot.zone_id == zone.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "ย้ายโซนไปสถานที่อื่นไม่ได้ เพราะมีช่องจอดผูกกับกล้องของสถานที่เดิมอยู่")
    for key, value in values.items():
        setattr(zone, key, value)
    db.add(AuditLog(user_id=admin.id, action="update_zone", target=zone.code))
    db.commit()
    db.refresh(zone)
    return zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    zone = _get_zone_or_404(db, zone_id)
    db.add(AuditLog(user_id=admin.id, action="delete_zone", target=zone.code))
    db.delete(zone)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "ลบไม่ได้ เพราะมีช่องจอดผูกกับโซนนี้อยู่")


@router.post("/{zone_id}/close", response_model=ZoneOut)
def close_zone(
    zone_id: int,
    data: ZoneCloseIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("zones", "override", "cameras")),
    _csrf: None = Depends(verify_csrf),
):
    """ปิด/เปิดโซนชั่วคราว พร้อมข้อความแจ้งประชาชน (TOR 4.2) — Admin และเจ้าหน้าที่ที่มีสิทธิ์โซนทำได้"""
    zone = ensure_zone(user, db.get(Zone, zone_id))
    note = (data.closed_note or "").strip() or None
    zone.is_closed = data.is_closed
    zone.closed_note = note if data.is_closed else None  # เปิดโซนคืน = ล้างข้อความแจ้งเดิม
    action = "close_zone" if data.is_closed else "reopen_zone"
    db.add(AuditLog(user_id=user.id, action=action, target=zone.code, detail={"note": zone.closed_note}))
    db.commit()
    db.refresh(zone)
    return zone


def _clean_zone(db: Session, data: ZoneIn) -> dict:
    """ตัดช่องว่างหน้า-หลัง และรหัสโซนเป็นตัวพิมพ์ใหญ่ (A, B, P1 ...) ให้รูปแบบเหมือนกันทั้งระบบ"""
    values = data.model_dump()
    values["code"] = values["code"].strip().upper()
    values["name_th"] = values["name_th"].strip()
    values["name_en"] = values["name_en"].strip()
    values["floor"] = (values["floor"] or "").strip() or None
    if not values["code"] or not values["name_th"] or not values["name_en"]:
        raise HTTPException(422, "ต้องใส่รหัสโซน ชื่อภาษาไทย และชื่อภาษาอังกฤษ")
    if values["site_id"] is None:
        site_ids = db.scalars(select(Site.id)).all()
        if len(site_ids) != 1:
            raise HTTPException(422, "กรุณาเลือกสถานที่ของโซนนี้")
        values["site_id"] = site_ids[0]
    elif db.get(Site, values["site_id"]) is None:
        raise HTTPException(422, "ไม่พบสถานที่ที่เลือก")
    return values


def _get_zone_or_404(db: Session, zone_id: int) -> Zone:
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบโซนนี้")
    return zone


def _check_code_not_taken(db: Session, code: str, site_id: int | None, exclude_zone_id: int | None = None) -> None:
    """รหัสโซนห้ามซ้ำภายในสถานที่เดียวกัน (สถานที่อื่นใช้รหัสเดียวกันได้)"""
    query = select(Zone).where(Zone.code == code, Zone.site_id == site_id)
    if exclude_zone_id is not None:
        query = query.where(Zone.id != exclude_zone_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"สถานที่นี้มีโซนรหัส '{code}' อยู่แล้ว")
