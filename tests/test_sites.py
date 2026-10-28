"""สิทธิ์รายสถานที่ และลิงก์นำทาง (TOR 4.6)"""
from core.sites import effective_site_ids, google_maps_directions_url, normalize_site_ids


def test_admin_always_sees_every_site():
    assert effective_site_ids("admin", [1]) is None
    assert normalize_site_ids("admin", [1], {1, 2}) is None


def test_restricted_user_sites():
    assert effective_site_ids("operator", None) is None  # ไม่จำกัด = ทุกแห่ง
    assert effective_site_ids("operator", [2, 1, 2]) == [1, 2]
    assert effective_site_ids("viewer", []) == []  # จำกัดแต่ไม่เลือก = ไม่เห็นเลย


def test_normalize_drops_unknown_sites():
    assert normalize_site_ids("operator", [1, 99, "2"], {1, 2, 3}) == [1, 2]
    assert normalize_site_ids("operator", None, {1, 2}) is None


def test_maps_url():
    assert google_maps_directions_url(None, 100.0) is None
    url = google_maps_directions_url(14.5289, 100.9101)
    assert url == "https://www.google.com/maps/dir/?api=1&destination=14.528900,100.910100"
