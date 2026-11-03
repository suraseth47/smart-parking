"""หน้าสถานะช่องจอดสด: ตัวอย่างหน้าสาธารณะแบบย่อ (web/routers/live.public_preview)"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db import Base
from core.models import Camera, CameraBrand, Site
from web.routers.live import public_preview


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_camera_without_site_is_not_shown():
    with _db() as db:
        cam = Camera(name="c1", brand=CameraBrand.TVT, host="10.0.0.1")
        db.add(cam); db.flush()
        out = public_preview(db, cam)
        assert out["shown"] is False and "ยังไม่ได้ผูกกับสถานที่" in out["note"]


def test_uncounted_and_hidden_site_explain_why():
    with _db() as db:
        site = Site(code="T1", name_th="ลานทดสอบ", name_en="Test", counted=False)
        db.add(site); db.flush()
        cam = Camera(name="c1", brand=CameraBrand.TVT, host="10.0.0.1", site_id=site.id)
        db.add(cam); db.flush()
        assert "ไม่นับรวม" in public_preview(db, cam)["note"]
        site.counted, site.is_public = True, False
        assert "ปิดการแสดง" in public_preview(db, cam)["note"]


def test_public_site_returns_summary_numbers():
    with _db() as db:
        site = Site(code="M1", name_th="ลานหน้าเทศบาล", name_en="Hall")
        db.add(site); db.flush()
        cam = Camera(name="c1", brand=CameraBrand.TVT, host="10.0.0.1", site_id=site.id, counted=False)
        db.add(cam); db.flush()
        out = public_preview(db, cam)
        assert out["shown"] is True and out["site_code"] == "M1" and out["status"] == "no_data"
        assert out["capacity"] == 0 and "กล้องนี้ตั้งเป็น" in out["note"]
