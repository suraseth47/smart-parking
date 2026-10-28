"""Reports: กราฟรายชั่วโมง/รายวัน/heatmap (FR-38) + ส่งออก Excel/CSV (TOR 4.5)

ฐานข้อมูลเก็บเวลาเป็น UTC — ทุก endpoint รับ/คืน "วันที่" และ "ชั่วโมง" เป็นเวลาท้องถิ่น (TZ ใน .env)
"""
from __future__ import annotations

import re

from datetime import date as date_type
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings, local_utc_offset_hours
from core.counting import COUNTABLE_TYPES
from core.db import get_db
from core.models import AuditLog, LayoutStatus, Site, Slot, SlotType, Zone, ZoneStatHour
from core.report_export import ReportMeta, ZoneReport, build_csv, build_xlsx
from core.reports import build_daily_report, build_heatmap_report, build_hourly_report
from web.deps import CurrentUser, require_permission
from web.site_access import ensure_zone, restrict

router = APIRouter(prefix="/api/admin/reports", tags=["reports"])

MAX_EXPORT_DAYS = 400


def _utc_window(day_from: date_type, day_to: date_type, offset_hours: float) -> tuple[datetime, datetime]:
    """ช่วงวันท้องถิ่น [day_from 00:00, day_to+1 00:00) -> ช่วงเวลา UTC สำหรับ query"""
    shift = timedelta(hours=offset_hours)
    start = datetime(day_from.year, day_from.month, day_from.day) - shift
    end = datetime(day_to.year, day_to.month, day_to.day) + timedelta(days=1) - shift
    return start, end


@router.get("/hourly")
def get_hourly_report(
    zone: int,
    date: date_type,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("reports")),
):
    ensure_zone(user, db.get(Zone, zone))
    offset = local_utc_offset_hours()
    day_start, day_end = _utc_window(date, date, offset)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct, ZoneStatHour.max_occ_pct, ZoneStatHour.samples)
        .where(
            ZoneStatHour.zone_id == zone,
            ZoneStatHour.hour_ts >= day_start,
            ZoneStatHour.hour_ts < day_end,
        )
    ).all()
    return build_hourly_report(rows, offset)


@router.get("/daily")
def get_daily_report(
    zone: int,
    from_: date_type = Query(..., alias="from"),
    to: date_type = Query(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("reports")),
):
    ensure_zone(user, db.get(Zone, zone))
    offset = local_utc_offset_hours()
    start, end = _utc_window(from_, to, offset)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct, ZoneStatHour.max_occ_pct)
        .where(ZoneStatHour.zone_id == zone, ZoneStatHour.hour_ts >= start, ZoneStatHour.hour_ts < end)
    ).all()
    return build_daily_report(rows, offset)


@router.get("/heatmap")
def get_heatmap_report(
    zone: int,
    weeks: int = Query(4, ge=1, le=104),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("reports")),
):
    ensure_zone(user, db.get(Zone, zone))
    start = datetime.utcnow() - timedelta(weeks=weeks)
    rows = db.execute(
        select(ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct)
        .where(ZoneStatHour.zone_id == zone, ZoneStatHour.hour_ts >= start)
    ).all()
    return build_heatmap_report(rows, local_utc_offset_hours())


@router.get("/export")
def export_report(
    from_: date_type = Query(..., alias="from"),
    to: date_type = Query(...),
    zone: str = "all",
    site_id: int | None = None,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("reports")),
):
    """ไฟล์รายงานอัตราการใช้งาน: xlsx = สรุป/รายวัน/รายชั่วโมง/Heatmap, csv = รายชั่วโมง"""
    if to < from_:
        raise HTTPException(422, "วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม")
    if (to - from_).days + 1 > MAX_EXPORT_DAYS:
        raise HTTPException(422, f"ส่งออกได้ครั้งละไม่เกิน {MAX_EXPORT_DAYS} วัน")

    if zone == "all":
        query = restrict(select(Zone), Zone.site_id, user)
        if site_id is not None:
            query = query.where(Zone.site_id == site_id)
        zones = db.scalars(query.order_by(Zone.site_id, Zone.sort_order, Zone.code)).all()
        if not zones:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่มีโซนให้ส่งออก")
    else:
        if not zone.isdigit():
            raise HTTPException(422, "zone ต้องเป็น all หรือรหัสตัวเลขของโซน")
        zones = [ensure_zone(user, db.get(Zone, int(zone)))]

    offset = local_utc_offset_hours()
    shift = timedelta(hours=offset)
    start, end = _utc_window(from_, to, offset)
    rows = db.execute(
        select(ZoneStatHour.zone_id, ZoneStatHour.hour_ts, ZoneStatHour.avg_occ_pct, ZoneStatHour.max_occ_pct, ZoneStatHour.samples)
        .where(ZoneStatHour.zone_id.in_([z.id for z in zones]), ZoneStatHour.hour_ts >= start, ZoneStatHour.hour_ts < end)
        .order_by(ZoneStatHour.hour_ts)
    ).all()
    capacity = dict(
        db.execute(
            select(Slot.zone_id, func.count())
            .where(
                Slot.layout_status == LayoutStatus.PUBLISHED,
                Slot.is_active.is_(True),
                Slot.type.in_([SlotType(t) for t in COUNTABLE_TYPES]),
            )
            .group_by(Slot.zone_id)
        ).all()
    )
    sites = {s.id: s for s in db.scalars(select(Site)).all()}
    multi_site = len({z.site_id for z in zones}) > 1
    reports = {
        z.id: ZoneReport(
            code=(f"{sites[z.site_id].code}/{z.code}" if multi_site and z.site_id in sites else z.code),
            name_th=(f"{sites[z.site_id].name_th} · {z.name_th}" if multi_site and z.site_id in sites else z.name_th),
            capacity=capacity.get(z.id, 0),
        )
        for z in zones
    }
    for zone_id, ts, avg, mx, n in rows:
        reports[zone_id].hours.append((ts + shift, avg, mx, n))
    zone_reports = list(reports.values())

    stamp = f"{from_:%Y%m%d}-{to:%Y%m%d}"
    scope = "all" if zone == "all" else (re.sub(r"[^A-Za-z0-9_-]", "", zones[0].code) or f"zone{zones[0].id}")
    if format == "csv":
        content = build_csv(zone_reports)
        media = "text/csv; charset=utf-8"
    else:
        meta = ReportMeta(
            site_name=(sites[zones[0].site_id].name_th if not multi_site and zones[0].site_id in sites
                       else "ทุกสถานที่" if multi_site else get_settings().site_name_th),
            date_from=from_,
            date_to=to,
            generated_at=datetime.utcnow() + shift,
            generated_by=user.username,
        )
        content = build_xlsx(meta, zone_reports)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = f"parking-report-{scope}-{stamp}.{format}"

    db.add(AuditLog(user_id=user.id, action="export_report", target=filename[:100],
                    detail={"from": str(from_), "to": str(to), "zone": scope, "format": format}))
    db.commit()
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _require_zone(db: Session, zone_id: int) -> None:
    if db.get(Zone, zone_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบโซนนี้")
