"""อีเมลแจ้งเตือนผู้ดูแล (core/alert_mail.py)"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import core.alert_mail as am
from core.db import Base
from core.models import Alert, AlertLevel, Setting, User, UserRole

NOW = datetime(2026, 11, 3, 3, 0)


def make_db(**cfg):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(User(username="a", password_hash="x", role=UserRole.ADMIN, email="Admin@Example.com"))
    db.add(User(username="o", password_hash="x", role=UserRole.OPERATOR, email="op@example.com"))
    db.add(Setting(key=am.ALERT_MAIL_KEY, value={"enabled": True, "delay_min": 5, **cfg}))
    db.flush()
    am.reset_retry()
    return db


def alert(db, source, minutes_ago, message="กล้อง X ขาดการเชื่อมต่อ"):
    a = Alert(level=AlertLevel.ERROR, source=source, message=message, created_at=NOW - timedelta(minutes=minutes_ago))
    db.add(a)
    db.flush()
    return a


def run(db):
    sent = []
    result = am.process_alert_mail(db, NOW, lambda to, c: sent.append((to, c)), "https://x/admin/alerts")
    return result, sent


def test_waits_for_delay_then_sends_once_to_admins_only():
    db = make_db(extra=["boss@example.com"])
    a = alert(db, "camera:1:connection", 2)
    assert run(db)[1] == []  # ยังไม่ถึง 5 นาที
    a.created_at = NOW - timedelta(minutes=6)
    result, sent = run(db)
    assert sorted(to for to, _ in sent) == ["admin@example.com", "boss@example.com"]
    assert "กล้องขาดการเชื่อมต่อ" in sent[0][1].subject
    assert a.emailed_at == NOW
    assert run(db)[1] == []  # ไม่ส่งซ้ำ


def test_resolved_mail_but_not_for_acknowledged():
    db = make_db()
    a = alert(db, "camera:1:moved", 30)
    b = alert(db, "camera:2:no_parking", 30, "รถจอดในเขตห้ามจอด 1 คัน")
    run(db)
    a.resolved_at = NOW
    b.resolved_at = NOW
    b.resolved_by = 1  # เจ้าหน้าที่กดรับทราบเอง
    result, sent = run(db)
    assert len(sent) == 1 and "กลับมาปกติ" in sent[0][1].subject and "นาน 30 นาที" in sent[0][1].text
    assert a.resolved_emailed_at == NOW and b.resolved_emailed_at == NOW


def test_disabled_kind_and_disabled_feature():
    db = make_db(kinds={"connection": False, "moved": True, "no_parking": True})
    alert(db, "camera:1:connection", 30)
    assert run(db)[1] == []
    db2 = make_db(enabled=False)
    alert(db2, "camera:1:moved", 30)
    assert run(db2)[0]["reason"] == "disabled"


def test_failure_waits_before_retry():
    db = make_db()
    a = alert(db, "camera:1:connection", 30)

    def boom(to, content):
        raise RuntimeError("smtp down")

    assert am.process_alert_mail(db, NOW, boom, None)["reason"] == "error"
    assert a.emailed_at is None
    assert am.process_alert_mail(db, NOW + timedelta(minutes=1), boom, None)["reason"] == "retry_wait"


def test_parse_extra():
    assert am.parse_extra("a@x.com, B@x.com\na@x.com") == ["a@x.com", "b@x.com"]
    with pytest.raises(ValueError):
        am.parse_extra("not-an-email")
