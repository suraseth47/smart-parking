"""จดจำการเข้าสู่ระบบ: ติ๊ก = คุกกี้ 30 วัน, ไม่ติ๊ก = 12 ชั่วโมง"""
import time

from fastapi import Response

from web.routers.auth import LoginRequest, set_auth_cookies
from web.session import REMEMBER_MAX_AGE_SECONDS, SESSION_MAX_AGE_SECONDS, create_session_cookie, read_session_cookie


def _max_ages(remember):
    r = Response()
    set_auth_cookies(r, user_id=1, role="admin", remember=remember)
    headers = [v.decode() for k, v in r.raw_headers if k == b"set-cookie"]
    return [int(h.split("Max-Age=")[1].split(";")[0]) for h in headers]


def test_default_is_12_hours():
    assert _max_ages(False) == [SESSION_MAX_AGE_SECONDS] * 2
    assert LoginRequest(username="a", password="b").remember is False


def test_remember_is_30_days():
    assert _max_ages(True) == [REMEMBER_MAX_AGE_SECONDS] * 2


def test_token_expiry_follows_max_age():
    payload = read_session_cookie(create_session_cookie(1, "admin", REMEMBER_MAX_AGE_SECONDS))
    assert payload["exp"] - time.time() > 29 * 24 * 3600
