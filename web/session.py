"""session cookie แบบเซ็นด้วย HMAC (stateless) และ CSRF token ตาม FR-40

ไม่เก็บ session ลง DB: ข้อมูลผู้ใช้ (user_id, role) เข้ารหัส+เซ็นอยู่ในคุกกี้เอง
ตรวจสอบตอนอ่านด้วย SECRET_KEY ว่าไม่ถูกปลอมแปลง
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from core.config import get_settings

SESSION_COOKIE_NAME = "session"
CSRF_COOKIE_NAME = "csrf_token"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60  # 12 ชั่วโมง


def create_session_cookie(user_id: int, role: str) -> str:
    """สร้างค่าคุกกี้ session ที่เซ็นด้วย SECRET_KEY ป้องกันการปลอมแปลง"""
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    return _sign(payload)


def read_session_cookie(cookie_value: str | None) -> dict | None:
    """ถอดค่าคุกกี้ session; คืน None ถ้าไม่มี/ถูกปลอมแปลง/หมดอายุ"""
    if not cookie_value:
        return None
    payload = _unsign(cookie_value)
    if payload is None or payload.get("exp", 0) < time.time():
        return None
    return payload


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _sign(payload: dict) -> str:
    secret_key = get_settings().secret_key.encode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(secret_key, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _unsign(token: str) -> dict | None:
    secret_key = get_settings().secret_key.encode()
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(secret_key, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        return json.loads(base64.urlsafe_b64decode(body.encode()))
    except (ValueError, UnicodeDecodeError):
        return None
