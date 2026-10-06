"""เชื่อมต่อฐานข้อมูล SQLite (WAL mode) และ session ให้ web/worker ใช้ร่วมกัน"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_settings


class Base(DeclarativeBase):
    """คลาสฐานของทุกตารางใน core/models.py"""


def _enable_wal_mode(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine():
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}")
    event.listen(engine, "connect", _enable_wal_mode)
    return engine


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: เปิด session แล้วปิดให้อัตโนมัติ"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
