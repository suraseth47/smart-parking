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
from core.models import Camera, Slot, SlotState, Zone
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
    state: str  # "free" | "occupied" | "unknown"


class ZoneSummaryOut(BaseModel):
    code: str
    name_th: str
    name_en: str
    status: str
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
                "free": z.free,
                "capacity": z.capacity,
                "free_disabled": z.free_disabled,
                "free_ev": z.free_ev,
                "slots": slot_maps.get(z.code),
            }
            for z in zone_summaries
        ],
    }


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
