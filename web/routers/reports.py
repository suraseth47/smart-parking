"""Reports: กราฟรายชั่วโมง/รายวัน/heatmap (FR-38)"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import Zone, ZoneStatHour
from core.reports import build_daily_report, build_heatmap_report, build_hourly_report
from web.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/api/admin/reports", tags=["reports"])


@router.get("/hourly")
def get_hourly_report(
    zone: int,
    date: date_type,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    _require_zone(db, zone)
    day_start = datetime(date.year, date.month, date.day)
    day_end = day_start + timedelta(days=1)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct, ZoneStatHour.max_occ_pct, ZoneStatHour.samples)
        .where(
            ZoneStatHour.zone_id == zone,
            ZoneStatHour.hour_ts >= day_start,
            ZoneStatHour.hour_ts < day_end,
        )
    ).all()
    return build_hourly_report(rows)


@router.get("/daily")
def get_daily_report(
    zone: int,
    from_: date_type = Query(..., alias="from"),
    to: date_type = Query(...),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    _require_zone(db, zone)
    start = datetime(from_.year, from_.month, from_.day)
    end = datetime(to.year, to.month, to.day) + timedelta(days=1)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct, ZoneStatHour.max_occ_pct)
        .where(ZoneStatHour.zone_id == zone, ZoneStatHour.hour_ts >= start, ZoneStatHour.hour_ts < end)
    ).all()
    return build_daily_report(rows)


@router.get("/heatmap")
def get_heatmap_report(
    zone: int,
    weeks: int = 4,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    _require_zone(db, zone)
    start = datetime.utcnow() - timedelta(weeks=weeks)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct)
        .where(ZoneStatHour.zone_id == zone, ZoneStatHour.hour_ts >= start)
    ).all()
    return build_heatmap_report(rows)


def _require_zone(db: Session, zone_id: int) -> None:
    if db.get(Zone, zone_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบโซนนี้")
