from datetime import datetime

from core.reports import build_daily_report, build_heatmap_report, build_hourly_report


def test_hourly_report_fills_missing_hours_with_zero():
    rows = [(datetime(2026, 1, 1, 9), 50.0, 80.0, 60), (datetime(2026, 1, 1, 10), 70.0, 90.0, 60)]
    points = build_hourly_report(rows)
    assert len(points) == 24
    assert points[9].avg_occ_pct == 50.0
    assert points[9].samples == 60
    assert points[10].avg_occ_pct == 70.0
    # ชั่วโมงอื่นไม่มีข้อมูล -> 0
    assert points[0].samples == 0
    assert points[0].avg_occ_pct == 0.0
    assert points[23].samples == 0


def test_hourly_report_order_matches_hour_number():
    rows = [(datetime(2026, 1, 1, 5), 10.0, 10.0, 1)]
    points = build_hourly_report(rows)
    assert [p.hour for p in points] == list(range(24))


def test_daily_report_averages_hours_within_each_day():
    rows = [
        (datetime(2026, 1, 1, 8), 40.0, 60.0),
        (datetime(2026, 1, 1, 9), 60.0, 80.0),
        (datetime(2026, 1, 2, 8), 100.0, 100.0),
    ]
    points = build_daily_report(rows)
    assert len(points) == 2
    assert points[0].date == "2026-01-01"
    assert points[0].avg_occ_pct == 50.0  # (40+60)/2
    assert points[0].max_occ_pct == 80.0
    assert points[1].date == "2026-01-02"
    assert points[1].avg_occ_pct == 100.0


def test_daily_report_sorted_by_date():
    rows = [
        (datetime(2026, 1, 3, 8), 10.0, 10.0),
        (datetime(2026, 1, 1, 8), 10.0, 10.0),
        (datetime(2026, 1, 2, 8), 10.0, 10.0),
    ]
    points = build_daily_report(rows)
    assert [p.date for p in points] == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_heatmap_groups_by_day_of_week_and_hour():
    # 2026-01-05 = จันทร์ (Monday), 2026-01-12 = จันทร์ถัดไป เวลาเดียวกัน
    rows = [
        (datetime(2026, 1, 5, 9), 40.0),  # จันทร์ 9:00
        (datetime(2026, 1, 12, 9), 60.0),  # จันทร์ 9:00 อีกสัปดาห์
        (datetime(2026, 1, 6, 9), 100.0),  # อังคาร 9:00
    ]
    cells = build_heatmap_report(rows)
    monday_9 = next(c for c in cells if c.day_of_week == 0 and c.hour == 9)
    tuesday_9 = next(c for c in cells if c.day_of_week == 1 and c.hour == 9)
    assert monday_9.avg_occ_pct == 50.0  # (40+60)/2
    assert tuesday_9.avg_occ_pct == 100.0


def test_heatmap_empty_input_returns_empty_list():
    assert build_heatmap_report([]) == []
