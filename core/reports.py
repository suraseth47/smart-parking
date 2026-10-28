"""รวมข้อมูล zone_stats_hour เป็นรายงานต่างๆ (FR-38) — pure function ไม่ยุ่งกับ DB"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class HourlyPoint:
    hour: int  # 0-23
    avg_occ_pct: float
    max_occ_pct: float
    samples: int


@dataclass
class DailyPoint:
    date: str  # YYYY-MM-DD
    avg_occ_pct: float
    max_occ_pct: float


@dataclass
class HeatmapCell:
    day_of_week: int  # 0=จันทร์ ... 6=อาทิตย์ (ตาม datetime.weekday())
    hour: int
    avg_occ_pct: float


def build_hourly_report(
    rows: list[tuple[datetime, float, float, int]], utc_offset_hours: float = 0.0
) -> list[HourlyPoint]:
    """rows: [(hour_ts แบบ UTC, avg_occ_pct, max_occ_pct, samples), ...] ของ 1 วัน -> เรียง 24 ชั่วโมง (0-23)

    ชั่วโมงในผลลัพธ์เป็นเวลาท้องถิ่น (UTC + utc_offset_hours)
    ชั่วโมงที่ไม่มีข้อมูล (ยังไม่มี slot publish/worker ยังไม่ได้รัน) จะได้ samples=0
    """
    shift = timedelta(hours=utc_offset_hours)
    by_hour = {(ts + shift).hour: (avg, mx, n) for ts, avg, mx, n in rows}
    points = []
    for hour in range(24):
        if hour in by_hour:
            avg, mx, n = by_hour[hour]
            points.append(HourlyPoint(hour=hour, avg_occ_pct=avg, max_occ_pct=mx, samples=n))
        else:
            points.append(HourlyPoint(hour=hour, avg_occ_pct=0.0, max_occ_pct=0.0, samples=0))
    return points


def build_daily_report(
    rows: list[tuple[datetime, float, float]], utc_offset_hours: float = 0.0
) -> list[DailyPoint]:
    """rows: [(hour_ts แบบ UTC, avg_occ_pct, max_occ_pct), ...] หลายวัน -> รวมเป็นรายวัน (ตามวันท้องถิ่น) เรียงตามวันที่"""
    shift = timedelta(hours=utc_offset_hours)
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for ts, avg, mx in rows:
        by_date[(ts + shift).strftime("%Y-%m-%d")].append((avg, mx))

    result = []
    for date_str in sorted(by_date.keys()):
        values = by_date[date_str]
        avg_pct = sum(v[0] for v in values) / len(values)
        max_pct = max(v[1] for v in values)
        result.append(DailyPoint(date=date_str, avg_occ_pct=avg_pct, max_occ_pct=max_pct))
    return result


def build_heatmap_report(rows: list[tuple[datetime, float]], utc_offset_hours: float = 0.0) -> list[HeatmapCell]:
    """rows: [(hour_ts, avg_occ_pct), ...] หลายสัปดาห์ -> เฉลี่ยตาม (วันในสัปดาห์, ชั่วโมง)

    ช่องที่ไม่มีข้อมูลเลยจะไม่อยู่ในผลลัพธ์ (ให้ frontend แสดงเป็น "ไม่มีข้อมูล" เอง
    แทนที่จะปลอมเป็น 0%)
    """
    shift = timedelta(hours=utc_offset_hours)
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for ts, avg in rows:
        local = ts + shift
        buckets[(local.weekday(), local.hour)].append(avg)

    return [
        HeatmapCell(day_of_week=dow, hour=hour, avg_occ_pct=sum(vals) / len(vals))
        for (dow, hour), vals in sorted(buckets.items())
    ]


@dataclass
class PeakPoint:
    hour: int  # 0-23 ตามเวลาท้องถิ่น
    avg_occ_pct: float


def build_public_peak(
    rows: list[tuple[datetime, float]], weekday: int, utc_offset_hours: float
) -> list[PeakPoint]:
    """กราฟ "ช่วงเวลาที่คนหนาแน่น" สำหรับหน้าสาธารณะ — pure function

    rows: [(hour_ts แบบ UTC, avg_occ_pct), ...] ของทุกโซนสาธารณะย้อนหลังหลายสัปดาห์
    weekday: วันที่ต้องการ (0=จันทร์ ... 6=อาทิตย์) ตามเวลาท้องถิ่น
    คืนค่าเฉลี่ย % การใช้งานรายชั่วโมงของวันนั้น เฉพาะชั่วโมงที่มีข้อมูล (ไม่ปลอมเป็น 0%)
    """
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts, avg in rows:
        local = ts + timedelta(hours=utc_offset_hours)
        if local.weekday() == weekday:
            buckets[local.hour].append(avg)
    return [
        PeakPoint(hour=hour, avg_occ_pct=round(sum(vals) / len(vals), 1))
        for hour, vals in sorted(buckets.items())
    ]
