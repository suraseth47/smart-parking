"""เมนูแสดงกล้องและช่องจอดจริง: ข้อมูลฝั่งประชาชนเฉพาะโซนที่กล้องมองเห็น"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db import Base
from core.models import Camera, CameraBrand, LayoutStatus, Site, Slot, SlotState, Zone
from web.deps import CurrentUser
from web.routers.showcase import get_showcase


def test_showcase_returns_camera_slots_and_public_zone_map():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        site = Site(code="M1", name_th="ลานหน้าเทศบาล", name_en="Hall")
        db.add(site); db.flush()
        za = Zone(site_id=site.id, code="A", name_th="โซน A", name_en="A")
        zb = Zone(site_id=site.id, code="B", name_th="โซน B", name_en="B")
        cam = Camera(name="c1", brand=CameraBrand.TVT, host="10.0.0.1", site_id=site.id)
        db.add_all([za, zb, cam]); db.flush()
        poly = [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1]]
        s1 = Slot(code="A-01", camera_id=cam.id, zone_id=za.id, polygon=poly, layout_status=LayoutStatus.PUBLISHED)
        db.add(s1); db.flush()
        db.add(SlotState(slot_id=s1.id, state="free")); db.flush()
        user = CurrentUser(id=1, username="admin", role="admin", permissions=["cctv"], site_ids=None)
        out = get_showcase(cam.id, db=db, user=user)
        assert [s["code"] for s in out["slots"]] == ["A-01"] and out["slots"][0]["state"] == "free"
        assert out["public"]["shown"] is True
        assert [z["code"] for z in out["public"]["zones"]] == ["A"]  # โซน B กล้องนี้ไม่เห็น ไม่ต้องแสดง
        assert out["public"]["zones"][0]["slots"][0]["code"] == "A-01"


def test_style_setting_defaults_to_grid_and_accepts_ring():
    from core.models import Setting
    from web.routers.showcase import SHOWCASE_KEY, load_showcase

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert load_showcase(db) == {"style": "grid"}
        db.add(Setting(key=SHOWCASE_KEY, value={"style": "ring"})); db.flush()
        assert load_showcase(db) == {"style": "ring"}
        db.get(Setting, SHOWCASE_KEY).value = {"style": "weird"}; db.flush()
        assert load_showcase(db) == {"style": "grid"}
