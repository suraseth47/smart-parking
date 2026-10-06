"""hash รหัสผ่านผู้ใช้ (Argon2) และเข้ารหัสรหัสผ่านกล้อง (Fernet) ตาม FR-23, FR-40"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from core.config import get_settings

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """เข้ารหัสผ่านผู้ใช้ด้วย Argon2 เก็บลง users.password_hash"""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """ตรวจรหัสผ่านตอน login; คืน False ถ้าไม่ตรงหรือ hash เสีย"""
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _get_fernet() -> Fernet:
    fernet_key = get_settings().fernet_key
    return Fernet(fernet_key.encode())


def encrypt_camera_password(plain_password: str) -> str:
    """เข้ารหัสรหัสผ่านกล้องก่อนเก็บลง cameras.password_enc ตาม FR-23"""
    return _get_fernet().encrypt(plain_password.encode()).decode()


def decrypt_camera_password(encrypted_password: str) -> str:
    """ถอดรหัสผ่านกล้องตอนจะต่อ RTSP จริง"""
    return _get_fernet().decrypt(encrypted_password.encode()).decode()
