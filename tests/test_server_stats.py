"""แถบสถานะ Server (core/server_stats.py) — ส่วนตัดสินระดับและคำนวณ"""
from collections import namedtuple

from core.server_stats import ai_level, ai_load_percent, level, pick_cpu_temperature

T = namedtuple("T", "label current high critical")


def test_level_thresholds():
    assert level("cpu", 30) == "ok"
    assert level("cpu", 75) == "warn"
    assert level("cpu", 95) == "crit"
    assert level("temp", None) == "none"


def test_ai_load_sums_all_cameras():
    # 3 กล้อง ใช้ 600 ms ทุก 30 วิ = 2% ต่อกล้อง รวม 6%
    assert ai_load_percent([600, 600, 600], [30, 30, 30]) == 6.0
    assert ai_load_percent([None, 900], [30, 30]) == 3.0
    assert ai_load_percent([], []) is None
    assert ai_level(85) == "crit" and ai_level(55) == "warn" and ai_level(5) == "ok" and ai_level(None) == "none"


def test_pick_cpu_temperature_prefers_cpu_sensor():
    sensors = {"nvme": [T("Composite", 39.0, None, None)], "coretemp": [T("Package id 0", 55.0, 80, 100), T("Core 0", 52.0, 80, 100)]}
    assert pick_cpu_temperature(sensors) == 55.0


def test_pick_cpu_temperature_falls_back_and_ignores_bad_values():
    assert pick_cpu_temperature({"acpi_x": [T("", 0.0, None, None), T("", 47.5, None, None)]}) == 47.5
    assert pick_cpu_temperature({}) is None
