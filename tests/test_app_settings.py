"""ค่าตั้ง ระบบและการแสดงผล: ค่าเริ่มต้น, รวมกับค่าที่บันทึก, กันค่าเกินขอบเขต"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.app_settings import (
    DISPLAY_SETTING_KEY,
    HEALTH_SETTING_KEY,
    PUBLIC_TOGGLES,
    load_display,
    load_health,
    save_setting,
)
from core.models import Base
from worker.health import is_health_check_due


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_defaults_without_saved_value(db):
    display = load_display(db)
    assert display["show_system_title"] is True
    assert display["public"] == PUBLIC_TOGGLES
    health = load_health(db)
    assert health == {"moved_check_enabled": True, "moved_check_interval_min": 10, "moved_threshold_px": 50}


def test_saved_values_merge_and_ignore_unknown_keys(db):
    save_setting(db, DISPLAY_SETTING_KEY, {
        "org_name": "เทศบาลเมืองสระบุรี", "show_server_address": False,
        "public": {"peak_chart": False, "unknown": True}, "hacker": "x",
    })
    db.commit()
    display = load_display(db)
    assert display["org_name"] == "เทศบาลเมืองสระบุรี"
    assert display["show_server_address"] is False
    assert display["show_sidebar_footer"] is True  # ไม่ได้บันทึก = ค่าเริ่มต้น
    assert display["public"]["peak_chart"] is False
    assert display["public"]["slot_map"] is True
    assert "unknown" not in display["public"] and "hacker" not in display


def test_health_values_are_clamped(db):
    save_setting(db, HEALTH_SETTING_KEY, {"moved_check_interval_min": 0, "moved_threshold_px": 9999, "moved_check_enabled": False})
    db.commit()
    health = load_health(db)
    assert health["moved_check_interval_min"] == 1
    assert health["moved_threshold_px"] == 300
    assert health["moved_check_enabled"] is False


def test_health_interval_is_used():
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    now = datetime(2026, 10, 28, 12, 0)
    cam = SimpleNamespace(last_health_check_at=now - timedelta(minutes=3))
    assert not is_health_check_due(cam, now, 10)
    assert is_health_check_due(cam, now, 2)
    assert is_health_check_due(SimpleNamespace(last_health_check_at=None), now, 10)  # ปุ่ม "ตรวจเดี๋ยวนี้" ล้างค่านี้
