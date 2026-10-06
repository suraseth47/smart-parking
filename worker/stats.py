"""บันทึกสรุปสถิติรายนาที/ชั่วโมงต่อโซน + ลบข้อมูลเก่าตาม retention (FR-36, 37, 39, FR-10)"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import (
    LayoutStatus,
    OccupancyState,
    Slot,
    SlotEvent,
    SlotState,
    Zone,
    ZoneStatHour,
    ZoneStatMinute,
)

MINUTE_RETENTION_DAYS = 30  # FR-39
HOUR_RETENTION_DAYS = 365 * 2  # FR-39
SLOT_EVENT_RETENTION_DAYS = 30  # FR-10

_last_minute_recorded: datetime | None = None
_last_pruned_date = None


def maybe_record_minute_stats(db: Session, now: datetime) -> None:
    """เรียกได้ทุกรอบ worker แต่จะบันทึกจริงแค่ตอนข้ามนาทีใหม่เท่านั้น (FR-36)"""
    global _last_minute_recorded
    minute_ts = now.replace(second=0, microsecond=0)
    if _last_minute_recorded == minute_ts:
        return
    record_minute_stats(db, minute_ts)
    _last_minute_recorded = minute_ts


def maybe_prune_old_stats(db: Session, now: datetime) -> None:
    """เรียกได้ทุกรอบ worker แต่จะลบข้อมูลเก่าจริงแค่วันละครั้ง"""
    global _last_pruned_date
    today = now.date()
    if _last_pruned_date == today:
        return
    prune_old_stats(db, now)
    _last_pruned_date = today


def record_minute_stats(db: Session, minute_ts: datetime) -> None:
    """บันทึกสรุปต่อโซน ณ นาทีนี้ (FR-36) แล้วอัปเดตยอดรวมรายชั่วโมงของชั่วโมงนั้น (FR-37)"""
    zones = db.scalars(select(Zone)).all()

    for zone in zones:
        states = db.scalars(
            select(SlotState.state)
            .join(Slot, Slot.id == SlotState.slot_id)
            .where(
                Slot.zone_id == zone.id,
                Slot.layout_status == LayoutStatus.PUBLISHED,
                Slot.is_active.is_(True),
            )
        ).all()

        total = len(states)
        occupied = sum(1 for s in states if s == OccupancyState.OCCUPIED)
        free = sum(1 for s in states if s == OccupancyState.FREE)
        unknown = total - occupied - free

        row = db.get(ZoneStatMinute, (minute_ts, zone.id))
        if row is None:
            row = ZoneStatMinute(ts=minute_ts, zone_id=zone.id)
            db.add(row)
        row.total = total
        row.occupied = occupied
        row.free = free
        row.unknown = unknown

        _update_hour_rollup(db, zone.id, minute_ts)


def compute_hour_rollup(minute_samples: list[tuple[int, int]]) -> tuple[float, float, int] | None:
    """minute_samples: [(occupied, total), ...] ของ 1 ชั่วโมง -> (avg_occ_pct, max_occ_pct, samples)

    ข้ามแถวที่ total=0 (ยังไม่มีช่อง publish ในโซนนั้น); คืน None ถ้าไม่มีตัวอย่างที่ใช้ได้เลย (FR-37)
    """
    occ_pcts = [occupied / total * 100 for occupied, total in minute_samples if total > 0]
    if not occ_pcts:
        return None
    return (sum(occ_pcts) / len(occ_pcts), max(occ_pcts), len(occ_pcts))


def _update_hour_rollup(db: Session, zone_id: int, minute_ts: datetime) -> None:
    hour_ts = minute_ts.replace(minute=0, second=0, microsecond=0)
    minute_rows = db.scalars(
        select(ZoneStatMinute).where(
            ZoneStatMinute.zone_id == zone_id,
            ZoneStatMinute.ts >= hour_ts,
            ZoneStatMinute.ts < hour_ts + timedelta(hours=1),
        )
    ).all()

    rollup = compute_hour_rollup([(m.occupied, m.total) for m in minute_rows])
    if rollup is None:
        return
    avg_occ_pct, max_occ_pct, samples = rollup

    hour_row = db.get(ZoneStatHour, (hour_ts, zone_id))
    if hour_row is None:
        hour_row = ZoneStatHour(hour_ts=hour_ts, zone_id=zone_id)
        db.add(hour_row)
    hour_row.avg_occ_pct = avg_occ_pct
    hour_row.max_occ_pct = max_occ_pct
    hour_row.samples = samples


def prune_old_stats(db: Session, now: datetime) -> None:
    """ลบข้อมูลเก่ากว่า retention ที่กำหนด (FR-39: รายนาที 30 วัน, รายชั่วโมง 2 ปี; FR-10: event 30 วัน)"""
    db.query(ZoneStatMinute).filter(
        ZoneStatMinute.ts < now - timedelta(days=MINUTE_RETENTION_DAYS)
    ).delete()
    db.query(ZoneStatHour).filter(
        ZoneStatHour.hour_ts < now - timedelta(days=HOUR_RETENTION_DAYS)
    ).delete()
    db.query(SlotEvent).filter(
        SlotEvent.ts < now - timedelta(days=SLOT_EVENT_RETENTION_DAYS)
    ).delete()
