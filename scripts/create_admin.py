"""สร้างบัญชี Admin คนแรก (ไม่มีรหัสผ่านตั้งต้น) ตาม FR-42

วิธีใช้: python scripts/create_admin.py
"""
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import SessionLocal
from core.models import User, UserRole
from core.security import hash_password

MIN_PASSWORD_LENGTH = 8


def main() -> None:
    username = input("Username: ").strip()
    if not username:
        print("ต้องใส่ username")
        return

    password = getpass("Password: ")
    password_confirm = getpass("Confirm password: ")
    if password != password_confirm:
        print("รหัสผ่านไม่ตรงกัน")
        return
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร")
        return

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            print(f"มีผู้ใช้ชื่อ '{username}' อยู่แล้ว")
            return

        user = User(username=username, password_hash=hash_password(password), role=UserRole.ADMIN)
        db.add(user)
        db.commit()
        print(f"สร้างบัญชี Admin '{username}' สำเร็จ")
    finally:
        db.close()


if __name__ == "__main__":
    main()
