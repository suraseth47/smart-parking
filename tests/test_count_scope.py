"""ไม่นับกล้อง/สถานที่ทดสอบในยอดช่องจอด (core/count_scope.py)"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.count_scope import counted_slots, uncounted_camera_ids
from core.db import Base
from core.models import Camera, CameraBrand, Site, Slot, Zone


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    a = Site(code="A", name_th="ลาน A", name_en="A")
    b = Site(code="B", name_th="ลาน B", name_en="B")
    db.add_all([a, b])
    db.flush()
    za = Zone(site_id=a.id, code="A", name_th="A", name_en="A")
    zb = Zone(site_id=b.id, code="B", name_th="B", name_en="B")
    db.add_all([za, zb])
    db.flush()
    cams = {
        "real": Camera(site_id=a.id, name="real", brand=CameraBrand.TVT, host="1"),
        "test": Camera(site_id=a.id, name="ValidationTestCam", brand=CameraBrand.TVT, host="2", counted=False),
        "b": Camera(site_id=b.id, name="b", brand=CameraBrand.TVT, host="3"),
    }
    db.add_all(cams.values())
    db.flush()
    for i, cam in enumerate(cams.values()):
        db.add(Slot(code=f"S{i}", camera_id=cam.id, zone_id=za.id if cam.site_id == a.id else zb.id, polygon=[[0, 0], [1, 0], [1, 1]]))
    db.flush()
    return db, a, b, cams


def counted_codes(db):
    return sorted(db.scalars(select(Slot.code).where(counted_slots(db))).all())


def test_uncounted_camera_is_excluded():
    db, _a, _b, cams = make_db()
    assert uncounted_camera_ids(db) == {cams["test"].id}
    assert counted_codes(db) == ["S0", "S2"]


def test_uncounted_site_excludes_all_its_cameras():
    db, _a, b, cams = make_db()
    b.counted = False
    db.flush()
    assert uncounted_camera_ids(db) == {cams["test"].id, cams["b"].id}
    assert counted_codes(db) == ["S0"]


def test_everything_counted_by_default():
    db, _a, _b, cams = make_db()
    cams["test"].counted = True
    db.flush()
    assert uncounted_camera_ids(db) == set()
    assert counted_codes(db) == ["S0", "S1", "S2"]
