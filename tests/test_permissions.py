"""สิทธิ์รายเมนู: เพดานตามบทบาท, ติ๊กลดได้แต่เพิ่มเกินบทบาทไม่ได้, Admin ได้ทุกเมนูเสมอ"""
from core.permissions import ALL_KEYS, effective_permissions, has_any_permission, normalize_permissions


def test_role_defaults():
    assert effective_permissions("admin", None) == list(ALL_KEYS)
    assert effective_permissions("operator", None) == ["live", "cctv", "override", "reports"]
    assert effective_permissions("viewer", None) == ["live", "reports"]
    assert effective_permissions("unknown", None) == []


def test_custom_can_only_reduce():
    assert effective_permissions("operator", ["live", "reports"]) == ["live", "reports"]
    assert effective_permissions("viewer", ["live", "cctv", "users"]) == ["live"]  # เกินบทบาทถูกตัด


def test_admin_always_full():
    assert effective_permissions("admin", ["live"]) == list(ALL_KEYS)
    assert normalize_permissions("admin", ["live"]) is None


def test_normalize_stores_none_when_full():
    assert normalize_permissions("operator", ["live", "cctv", "override", "reports"]) is None
    assert normalize_permissions("operator", ["reports", "live", "users"]) == ["live", "reports"]
    assert normalize_permissions("viewer", None) is None


def test_has_any_permission():
    assert has_any_permission("operator", ["live"], ("live", "cameras"))
    assert not has_any_permission("operator", ["live"], ("cctv",))
