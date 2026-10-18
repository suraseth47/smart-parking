from datetime import datetime

from core.reports import build_public_peak

# 2026-10-18 เป็นวันอาทิตย์ (weekday=6)


def test_peak_converts_utc_to_local_hour():
    rows = [(datetime(2026, 10, 18, 2, 0), 80.0)]  # 02:00 UTC = 09:00 เวลาไทย
    result = build_public_peak(rows, weekday=6, utc_offset_hours=7)
    assert [(p.hour, p.avg_occ_pct) for p in result] == [(9, 80.0)]


def test_peak_filters_by_local_weekday():
    rows = [
        (datetime(2026, 10, 17, 18, 0), 50.0),  # เสาร์ 18:00 UTC = อาทิตย์ 01:00 เวลาไทย
        (datetime(2026, 10, 17, 10, 0), 90.0),  # เสาร์ 17:00 เวลาไทย -> ไม่นับ
    ]
    result = build_public_peak(rows, weekday=6, utc_offset_hours=7)
    assert [(p.hour, p.avg_occ_pct) for p in result] == [(1, 50.0)]


def test_peak_averages_same_hour_across_weeks_and_zones():
    rows = [
        (datetime(2026, 10, 18, 3, 0), 40.0),
        (datetime(2026, 10, 11, 3, 0), 60.0),
    ]
    result = build_public_peak(rows, weekday=6, utc_offset_hours=7)
    assert [(p.hour, p.avg_occ_pct) for p in result] == [(10, 50.0)]


def test_peak_empty_when_no_data():
    assert build_public_peak([], weekday=0, utc_offset_hours=7) == []
