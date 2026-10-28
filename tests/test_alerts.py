"""ตรวจ "ระบบทำงานผิดปกติ" ที่คำนวณสด (worker หยุด / ดิสก์ใกล้เต็ม)"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from web.routers.health import system_warnings

NOW = datetime(2026, 10, 28, 9, 0)


def cam(enabled=True, minutes_ago=None):
    last = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    return SimpleNamespace(enabled=enabled, last_frame_at=last)


def test_no_warning_when_worker_recent():
    assert system_warnings([cam(minutes_ago=1), cam(minutes_ago=30)], NOW, 50.0) == []


def test_worker_stale_when_every_camera_is_old():
    warnings = system_warnings([cam(minutes_ago=12), cam(minutes_ago=40)], NOW, 50.0)
    assert [w["key"] for w in warnings] == ["worker_stale"]
    assert "12 นาที" in warnings[0]["message"]


def test_disabled_cameras_are_ignored():
    assert system_warnings([cam(enabled=False, minutes_ago=600)], NOW, None) == []


def test_disk_warning():
    assert [w["key"] for w in system_warnings([], NOW, 93.5)] == ["disk_full"]
