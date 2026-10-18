"""หน้าเว็บสาธารณะ + API สรุปที่ว่าง (FR-16..20)"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.counting import SlotInfo, ZoneInfo, build_public_summary, build_slot_maps
from core.db import get_db
from core.models import Camera, Slot, SlotState, Zone, ZoneStatHour
from core.reports import build_public_peak
from web.templates_env import templates

router = APIRouter(tags=["public"])

CACHE_TTL_SECONDS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 60
STALE_AFTER_SECONDS = 180  # ทั้งระบบไม่อัปเดตเกิน 3 นาที -> stale (FR-16)

_cache: dict | None = None
_cache_at: float = 0.0
_rate_limit_hits: dict[str, list[float]] = {}


class SiteOut(BaseModel):
    name_th: str
    name_en: str


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
    updated_at: str | None
    stale: bool
    total: TotalOut
    zones: list[ZoneSummaryOut]


@router.get("/", include_in_schema=False)
def public_page(request: Request):
    return templates.TemplateResponse(request, "public/index.html")


@router.get("/healthz")
def healthz():
    """สถานะระบบแบบย่อสำหรับ monitoring"""
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@router.get("/api/public/summary", response_model=PublicSummaryOut)
def get_public_summary(request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    cached = _get_cached()
    if cached is not None:
        return cached

    result = _build_summary(db)
    _set_cached(result)
    return result


def _build_summary(db: Session) -> dict:
    settings = get_settings()

    zones = db.scalars(select(Zone)).all()
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

    latest_update = db.scalar(select(func.max(Camera.last_frame_at)).where(Camera.enabled.is_(True)))
    stale = latest_update is None or (
        datetime.utcnow() - latest_update > timedelta(seconds=STALE_AFTER_SECONDS)
    )

    return {
        "site": {"name_th": settings.site_name_th, "name_en": settings.site_name_en},
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
_peak_cache: dict | None = None
_peak_cache_at: float = 0.0


class PeakPointOut(BaseModel):
    hour: int
    avg_occ_pct: float


class PublicPeakOut(BaseModel):
    weekday: int  # 0=จันทร์ ... 6=อาทิตย์ (เวลาท้องถิ่น)
    now_hour: int
    weeks: int
    points: list[PeakPointOut]


@router.get("/api/public/peak", response_model=PublicPeakOut)
def get_public_peak(request: Request, db: Session = Depends(get_db)):
    """ช่วงเวลาที่คนหนาแน่นของ "วันนี้" (เฉลี่ยวันเดียวกันย้อนหลัง 4 สัปดาห์) ทุกโซนสาธารณะรวมกัน

    เป็นตัวเลขรวม % การใช้งานเท่านั้น ไม่มีข้อมูลส่วนบุคคล
    """
    global _peak_cache, _peak_cache_at
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    if _peak_cache is not None and (time.monotonic() - _peak_cache_at) < PEAK_CACHE_TTL_SECONDS:
        return _peak_cache

    offset_hours = _local_utc_offset_hours()
    local_now = datetime.utcnow() + timedelta(hours=offset_hours)
    public_zone_ids = select(Zone.id).where(Zone.is_public.is_(True))
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
    _peak_cache, _peak_cache_at = result, time.monotonic()
    return result


def _local_utc_offset_hours() -> float:
    """ค่า offset ของเขตเวลาใน .env (TZ) เทียบ UTC; ถ้าอ่านไม่ได้ใช้ +7 (ประเทศไทย)"""
    try:
        from zoneinfo import ZoneInfo as TzZoneInfo

        offset = datetime.now(TzZoneInfo(get_settings().tz)).utcoffset()
        return offset.total_seconds() / 3600 if offset is not None else 7.0
    except Exception:
        return 7.0


def _get_cached() -> dict | None:
    if _cache is not None and (time.monotonic() - _cache_at) < CACHE_TTL_SECONDS:
        return _cache
    return None


def _set_cached(result: dict) -> None:
    global _cache, _cache_at
    _cache = result
    _cache_at = time.monotonic()


def _check_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    hits = _rate_limit_hits.setdefault(client_ip, [])
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "ขอข้อมูลถี่เกินไป กรุณาลองใหม่ภายหลัง")
    hits.append(now)
