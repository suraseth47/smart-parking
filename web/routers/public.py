"""หน้าเว็บสาธารณะ + API สรุปที่ว่าง (FR-16..20)"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.app_settings import LOGO_TYPES, cached_display, logo_dir
from core.config import local_utc_offset_hours
from core.counting import SlotInfo, ZoneInfo, build_public_summary, build_slot_maps
from core.db import get_db
from core.models import Camera, Site, Slot, SlotState, Zone, ZoneStatHour
from core.sites import google_maps_directions_url
from core.reports import build_public_peak
from web.templates_env import templates

router = APIRouter(tags=["public"])

CACHE_TTL_SECONDS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
# 240 ครั้ง/นาที/IP: มือถือ 1 เครื่องเรียกราว 3 ครั้ง/นาที — เผื่อคนจำนวนมากที่ออกเน็ตผ่าน IP เดียวกัน
# (Wi-Fi สำนักงาน/มือถือเครือข่ายเดียวกัน) แต่ยังกันการยิงคำขอถี่ๆ ได้
RATE_LIMIT_MAX_REQUESTS = 240
STALE_AFTER_SECONDS = 180  # ทั้งระบบไม่อัปเดตเกิน 3 นาที -> stale (FR-16)

_cache: dict[str, tuple[float, dict]] = {}  # key = รหัสสถานที่ (หรือ "__sites__" สำหรับรายการสถานที่)
_rate_limit_hits: dict[str, list[float]] = {}


class SiteOut(BaseModel):
    name_th: str
    name_en: str
    code: str | None = None
    address: str | None = None
    opening_hours: str | None = None
    maps_url: str | None = None


class TotalOut(BaseModel):
    free: int
    capacity: int
    free_disabled: int
    free_ev: int
    excluded_zones: list[str]


class SlotBoxOut(BaseModel):
    code: str
    state: str  # "free" | "occupied" | "unknown" | "locked" (ช่อง reserved ไม่นับยอด)
    type: str = "normal"  # "normal" | "disabled" | "ev" | "reserved"


class ZoneSummaryOut(BaseModel):
    code: str
    name_th: str
    name_en: str
    status: str
    closed_note: str | None = None
    free: int | None = None
    capacity: int | None = None
    free_disabled: int | None = None
    free_ev: int | None = None
    slots: list[SlotBoxOut] | None = None


class PublicSummaryOut(BaseModel):
    site: SiteOut
    site_count: int = 1  # จำนวนสถานที่สาธารณะทั้งหมด (>1 = หน้าเว็บแสดงปุ่มกลับไปรายการสถานที่)
    updated_at: str | None
    stale: bool
    total: TotalOut
    zones: list[ZoneSummaryOut]


@router.get("/", include_in_schema=False)
def public_page(request: Request):
    return templates.TemplateResponse(request, "public/index.html")


@router.get("/branding/logo", include_in_schema=False)
def branding_logo():
    """โลโก้ที่อัปโหลดจากหน้า ตั้งค่าระบบ (เปิดได้ไม่ต้อง login เพราะหน้าเข้าสู่ระบบใช้ด้วย)"""
    name = cached_display().get("logo_file") or ""
    path = logo_dir() / name
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if not name or ext not in LOGO_TYPES or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่มีโลโก้")
    return FileResponse(
        path, media_type=LOGO_TYPES[ext],
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/healthz")
def healthz():
    """สถานะระบบแบบย่อสำหรับ monitoring"""
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


class PublicSiteOut(BaseModel):
    code: str
    name_th: str
    name_en: str
    address: str | None
    opening_hours: str | None
    maps_url: str | None
    latitude: float | None
    longitude: float | None
    status: str  # "ok" | "full" | "no_data" | "closed" | "stale"
    free: int
    capacity: int
    free_disabled: int
    free_ev: int
    stale: bool
    updated_at: str | None


@router.get("/api/public/sites", response_model=list[PublicSiteOut])
def get_public_sites(request: Request, db: Session = Depends(get_db)):
    """รายการสถานที่จอดรถทั้งหมด พร้อมจำนวนช่องว่างของแต่ละแห่ง (TOR 4.6)"""
    _check_rate_limit(request.client.host if request.client else "unknown")
    cached = _get_cached("__sites__")
    if cached is not None:
        return cached
    result = []
    for site in _public_sites(db):
        summary = _build_summary(db, site, site_count=0)
        total = summary["total"]
        statuses = [z["status"] for z in summary["zones"]]
        if statuses and all(s == "closed" for s in statuses):
            status_text = "closed"
        elif total["capacity"] == 0 and not summary["updated_at"]:
            status_text = "no_data"  # ยังไม่ติดตั้งกล้อง/ยังไม่มีช่องจอด
        elif summary["stale"]:
            status_text = "stale"
        elif total["capacity"] == 0:
            status_text = "no_data"
        elif total["free"] == 0:
            status_text = "full"
        else:
            status_text = "ok"
        result.append({
            "code": site.code, "name_th": site.name_th, "name_en": site.name_en,
            "address": site.address, "opening_hours": site.opening_hours,
            "maps_url": google_maps_directions_url(site.latitude, site.longitude),
            "latitude": site.latitude, "longitude": site.longitude,
            "status": status_text, "free": total["free"], "capacity": total["capacity"],
            "free_disabled": total["free_disabled"], "free_ev": total["free_ev"],
            "stale": summary["stale"], "updated_at": summary["updated_at"],
        })
    _set_cached("__sites__", result)
    return result


@router.get("/api/public/summary", response_model=PublicSummaryOut)
def get_public_summary(request: Request, site: str | None = None, db: Session = Depends(get_db)):
    """ยอดว่างของสถานที่เดียว — ไม่ระบุ site = สถานที่แรก (ระบบที่มีสถานที่เดียวใช้แบบเดิมได้)"""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    sites = _public_sites(db)
    if not sites:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ยังไม่มีสถานที่ที่เปิดให้บริการ")
    chosen = sites[0] if site is None else next((s for s in sites if s.code == site.upper()), None)
    if chosen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบสถานที่นี้")

    cached = _get_cached(chosen.code)
    if cached is not None:
        return cached
    result = _build_summary(db, chosen, site_count=len(sites))
    _set_cached(chosen.code, result)
    return result


def _public_sites(db: Session) -> list[Site]:
    return list(db.scalars(select(Site).where(Site.is_public.is_(True)).order_by(Site.sort_order, Site.id)).all())


def _build_summary(db: Session, site: Site, site_count: int) -> dict:
    """ยอดสาธารณะของ 1 สถานที่ — รวมทุกกล้องของสถานที่เป็นยอดเดียว

    ช่องจอดแต่ละช่องผูกกับกล้องตัวเดียว (ระบบห้ามวาดรหัสช่องซ้ำในสถานที่เดียวกัน)
    จึงไม่มีการนับช่องเดียวกันซ้ำแม้กล้องหลายตัวมองเห็นพื้นที่ทับซ้อนกัน
    """
    zones = db.scalars(select(Zone).where(Zone.site_id == site.id).order_by(Zone.sort_order, Zone.code)).all()
    zone_infos = [
        ZoneInfo(
            id=z.id, code=z.code, name_th=z.name_th, name_en=z.name_en,
            is_public=z.is_public, is_closed=z.is_closed,
        )
        for z in zones
    ]
    zone_names = {z.id: (z.name_th, z.name_en) for z in zones}
    zone_notes = {z.code: z.closed_note for z in zones}

    rows = db.execute(
        select(Slot.zone_id, Slot.code, Slot.type, Slot.is_active, Slot.layout_status, SlotState.state)
        .outerjoin(SlotState, SlotState.slot_id == Slot.id)
        .where(Slot.zone_id.in_([z.id for z in zones] or [-1]))
    ).all()
    slot_infos = [
        SlotInfo(
            zone_id=r.zone_id,
            code=r.code,
            type=r.type.value,
            state=r.state.value if r.state else "unknown",
            is_active=r.is_active,
            layout_status=r.layout_status.value,
        )
        for r in rows
    ]

    zone_summaries, total = build_public_summary(zone_infos, slot_infos)
    slot_maps = build_slot_maps(zone_infos, slot_infos)
    zone_id_by_code = {z.code: z.id for z in zones}

    # ข้อมูลไม่เป็นปัจจุบัน = กล้องทุกตัวของสถานที่นี้ไม่ได้อัปเดตเกิน 3 นาที
    # (กล้องหลุดบางตัว: เฉพาะช่องของกล้องนั้นเป็น "ไม่ทราบสถานะ" ส่วนช่องอื่นแสดงตามปกติ)
    latest_update = db.scalar(
        select(func.max(Camera.last_frame_at)).where(Camera.enabled.is_(True), Camera.site_id == site.id)
    )
    stale = latest_update is None or (
        datetime.utcnow() - latest_update > timedelta(seconds=STALE_AFTER_SECONDS)
    )

    return {
        "site": {
            "name_th": site.name_th, "name_en": site.name_en, "code": site.code,
            "address": site.address, "opening_hours": site.opening_hours,
            "maps_url": google_maps_directions_url(site.latitude, site.longitude),
        },
        "site_count": site_count,
        "updated_at": latest_update.isoformat() if latest_update else None,
        "stale": stale,
        "total": {
            "free": total.free,
            "capacity": total.capacity,
            "free_disabled": total.free_disabled,
            "free_ev": total.free_ev,
            "excluded_zones": total.excluded_zones,
        },
        "zones": [
            {
                "code": z.code,
                "name_th": zone_names[zone_id_by_code[z.code]][0],
                "name_en": zone_names[zone_id_by_code[z.code]][1],
                "status": z.status,
                "closed_note": zone_notes.get(z.code) if z.status == "closed" else None,
                "free": z.free,
                "capacity": z.capacity,
                "free_disabled": z.free_disabled,
                "free_ev": z.free_ev,
                "slots": slot_maps.get(z.code),
            }
            for z in zone_summaries
        ],
    }


PEAK_WEEKS = 4
PEAK_CACHE_TTL_SECONDS = 600
_peak_cache: dict[str, tuple[float, dict]] = {}


class PeakPointOut(BaseModel):
    hour: int
    avg_occ_pct: float


class PublicPeakOut(BaseModel):
    weekday: int  # 0=จันทร์ ... 6=อาทิตย์ (เวลาท้องถิ่น)
    now_hour: int
    weeks: int
    points: list[PeakPointOut]


@router.get("/api/public/peak", response_model=PublicPeakOut)
def get_public_peak(request: Request, site: str | None = None, db: Session = Depends(get_db)):
    """ช่วงเวลาที่คนหนาแน่นของ "วันนี้" (เฉลี่ยวันเดียวกันย้อนหลัง 4 สัปดาห์) ของสถานที่ที่เลือก

    เป็นตัวเลขรวม % การใช้งานเท่านั้น ไม่มีข้อมูลส่วนบุคคล
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    sites = _public_sites(db)
    chosen = (sites[0] if sites else None) if site is None else next((s for s in sites if s.code == site.upper()), None)
    if chosen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบสถานที่นี้")
    hit = _peak_cache.get(chosen.code)
    if hit is not None and (time.monotonic() - hit[0]) < PEAK_CACHE_TTL_SECONDS:
        return hit[1]

    offset_hours = local_utc_offset_hours()
    local_now = datetime.utcnow() + timedelta(hours=offset_hours)
    public_zone_ids = select(Zone.id).where(Zone.is_public.is_(True), Zone.site_id == chosen.id)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct).where(
            ZoneStatHour.zone_id.in_(public_zone_ids),
            ZoneStatHour.hour_ts >= datetime.utcnow() - timedelta(weeks=PEAK_WEEKS),
        )
    ).all()
    points = build_public_peak(rows, weekday=local_now.weekday(), utc_offset_hours=offset_hours)
    result = {
        "weekday": local_now.weekday(),
        "now_hour": local_now.hour,
        "weeks": PEAK_WEEKS,
        "points": [{"hour": p.hour, "avg_occ_pct": p.avg_occ_pct} for p in points],
    }
    _peak_cache[chosen.code] = (time.monotonic(), result)
    return result


def _get_cached(key: str) -> dict | list | None:
    hit = _cache.get(key)
    if hit is not None and (time.monotonic() - hit[0]) < CACHE_TTL_SECONDS:
        return hit[1]
    return None


def _set_cached(key: str, result) -> None:
    _cache[key] = (time.monotonic(), result)


def _check_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    hits = _rate_limit_hits.setdefault(client_ip, [])
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "ขอข้อมูลถี่เกินไป กรุณาลองใหม่ภายหลัง")
    hits.append(now)
