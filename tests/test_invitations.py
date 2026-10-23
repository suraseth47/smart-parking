"""คำเชิญผู้ใช้/ลิงก์ตั้งรหัสผ่าน: token, สถานะ, ตรวจข้อมูล, กันระบบไม่เหลือ Admin"""
from datetime import datetime, timedelta

from core.invitations import (
    can_change_admin,
    generate_token,
    hash_token,
    invitation_status,
    validate_email,
    validate_password,
    validate_username,
)

NOW = datetime(2026, 10, 23, 12, 0)


def test_tokens_are_random_and_hash_is_stable():
    a, b = generate_token(), generate_token()
    assert a != b and len(a) >= 40
    assert hash_token(a) == hash_token(a)
    assert hash_token(a) != a and len(hash_token(a)) == 64


def test_invitation_status_priority():
    later = NOW + timedelta(hours=1)
    earlier = NOW - timedelta(hours=1)
    assert invitation_status(None, None, later, NOW) == "pending"
    assert invitation_status(None, None, earlier, NOW) == "expired"
    assert invitation_status(None, NOW, later, NOW) == "revoked"
    assert invitation_status(NOW, NOW, earlier, NOW) == "accepted"  # ใช้แล้วสำคัญที่สุด


def test_validate_username():
    assert validate_username("somchai.j") is None
    assert validate_username("ab") is not None
    assert validate_username("สมชาย") is not None
    assert validate_username("a b c") is not None


def test_validate_password():
    assert validate_password("longenough1", "longenough1") is None
    assert validate_password("short", "short") is not None
    assert validate_password("longenough1", "different11") is not None


def test_validate_email_optional():
    assert validate_email(None) is None
    assert validate_email("a@naslink.net") is None
    assert validate_email("not-an-email") is not None


def test_cannot_remove_last_admin():
    assert not can_change_admin(1, True, "operator", None)
    assert not can_change_admin(1, True, None, False)
    assert can_change_admin(2, True, "viewer", None)
    assert can_change_admin(1, False, "viewer", False)  # คนนี้ไม่ใช่ admin อยู่แล้ว
    assert can_change_admin(1, True, "admin", True)
