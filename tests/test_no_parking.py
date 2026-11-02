"""เขตห้ามจอด / รถจอดซ้อนคัน (worker/no_parking.py)"""
from datetime import datetime, timedelta

import pytest

from worker.no_parking import (
    alert_message,
    footprint_zone,
    parked_tracks,
    summarize,
    update_tracks,
    validate_zones,
    zone_shape,
)

LANE = [[0.0, 0.5], [1.0, 0.5], [1.0, 0.7], [0.0, 0.7]]  # ทางวิ่งแนวนอนกลางภาพ
ZONES = [("lane", zone_shape(LANE))]
T0 = datetime(2026, 11, 3, 10, 0, 0)


def run_rounds(boxes_per_round, start=T0, step_s=30):
    tracks = []
    for i, boxes in enumerate(boxes_per_round):
        now = start + timedelta(seconds=step_s * i)
        detections = [(z, b) for b in boxes if (z := footprint_zone(b, ZONES))]
        tracks = update_tracks(tracks, detections, now)
    return tracks, now


def test_footprint_mostly_inside_zone_counts():
    assert footprint_zone((0.2, 0.55, 0.3, 0.65), ZONES) == "lane"


def test_footprint_mostly_outside_zone_is_ignored():
    # รถในช่องจอดที่แค่ท้ายยื่นเข้าทางวิ่งนิดเดียว ไม่นับ
    assert footprint_zone((0.2, 0.3, 0.3, 0.55), ZONES) is None


def test_parked_car_counts_after_dwell_time():
    car = (0.4, 0.55, 0.5, 0.65)
    tracks, now = run_rounds([[car]] * 11)  # 0..300 วินาที = 5 นาที
    assert len(parked_tracks(tracks, 5)) == 1
    assert len(parked_tracks(tracks, 6)) == 0


def test_moving_car_never_counts():
    # รถวิ่งผ่านทางวิ่ง ตำแหน่งเลื่อนไปทุกรอบ → เริ่มนับเวลาใหม่ทุกครั้ง
    rounds = [[(0.05 * i, 0.55, 0.05 * i + 0.04, 0.65)] for i in range(20)]
    tracks, _ = run_rounds(rounds)
    assert parked_tracks(tracks, 5) == []


def test_small_jitter_keeps_same_car():
    rounds = [[(0.40 + 0.003 * (i % 2), 0.55, 0.50 + 0.003 * (i % 2), 0.65)] for i in range(11)]
    tracks, _ = run_rounds(rounds)
    assert len(tracks) == 1 and len(parked_tracks(tracks, 5)) == 1


def test_missed_detection_two_rounds_is_tolerated_three_drops():
    car = (0.4, 0.55, 0.5, 0.65)
    tracks, _ = run_rounds([[car]] * 8 + [[]] * 2 + [[car]])
    assert len(parked_tracks(tracks, 5)) == 1  # AI พลาด 2 รอบ ยังเป็นคันเดิม
    tracks, _ = run_rounds([[car]] * 8 + [[]] * 3 + [[car]])
    assert parked_tracks(tracks, 5) == []  # หาย 3 รอบ = รถออกไปแล้ว คันที่มาใหม่เริ่มนับใหม่


def test_two_cars_side_by_side_are_two_tracks():
    a = (0.10, 0.55, 0.20, 0.65)
    b = (0.22, 0.55, 0.32, 0.65)
    tracks, _ = run_rounds([[a, b]] * 11)
    assert len(parked_tracks(tracks, 5)) == 2


def test_summary_and_message():
    zones = [{"id": "lane", "name": "ทางวิ่ง", "polygon": LANE}, {"id": "exit", "name": "หน้าทางออก", "polygon": LANE}]
    car = (0.4, 0.55, 0.5, 0.65)
    tracks, now = run_rounds([[car]] * 17)  # 8 นาที
    summary = summarize(zones, tracks, 5, now)
    assert summary == [{"id": "lane", "name": "ทางวิ่ง", "count": 1, "longest_min": 8}]
    msg = alert_message("ลานหน้าเทศบาล-1", summary, 5)
    assert msg == "กล้อง ลานหน้าเทศบาล-1: พบรถจอดในเขตห้ามจอด 1 คัน (ทางวิ่ง) จอดนานเกิน 5 นาที"


def test_validate_zones_cleans_and_rejects():
    clean = validate_zones([{"id": "a", "name": "  ทางวิ่ง ", "polygon": [[-0.1, 0.5], [1.2, 0.5], [1, 0.7]]}])
    assert clean[0]["name"] == "ทางวิ่ง"
    assert clean[0]["polygon"][0] == [0.0, 0.5] and clean[0]["polygon"][1] == [1.0, 0.5]
    with pytest.raises(ValueError):
        validate_zones([{"name": "x", "polygon": [[0, 0], [1, 1]]}])
    with pytest.raises(ValueError):
        validate_zones([{"name": "เส้นตรง", "polygon": [[0, 0], [0.5, 0.5], [1, 1]]}])


def test_process_opens_updates_and_closes_alert():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from core.db import Base
    from core.models import Alert, Camera, CameraBrand
    from worker.no_parking import process_no_parking

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        camera = Camera(name="ลานหน้าเทศบาล-1", brand=CameraBrand.TVT, host="10.0.0.1",
                        no_parking_zones=[{"id": "lane", "name": "ทางวิ่ง", "polygon": LANE}], no_parking_dwell_min=5)
        db.add(camera)
        db.flush()
        a, b = (0.10, 0.55, 0.20, 0.65), (0.40, 0.55, 0.50, 0.65)
        for i in range(11):
            process_no_parking(db, camera, [a], T0 + timedelta(seconds=30 * i))
        db.flush()
        alerts = db.scalars(select(Alert)).all()
        assert len(alerts) == 1 and "1 คัน (ทางวิ่ง)" in alerts[0].message
        first_id = alerts[0].id
        # คันที่ 2 จอดเพิ่ม → แก้ข้อความแจ้งเตือนเดิม ไม่เปิดใหม่
        for i in range(11, 22):
            process_no_parking(db, camera, [a, b], T0 + timedelta(seconds=30 * i))
        db.flush()
        alerts = db.scalars(select(Alert)).all()
        assert len(alerts) == 1 and alerts[0].id == first_id and "2 คัน" in alerts[0].message
        # รถออกหมด → หลัง 3 รอบปิดแจ้งเตือนเอง
        for i in range(22, 25):
            process_no_parking(db, camera, [], T0 + timedelta(seconds=30 * i))
        db.flush()
        assert db.scalars(select(Alert)).one().resolved_at is not None
