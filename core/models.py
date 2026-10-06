"""ตารางฐานข้อมูลตาม SPEC ข้อ 6

หมายเหตุ: มีตารางของ P1 (users, zones, cameras, slots, slot_state,
slot_events, settings, audit_log) และ P2 (zone_stats_minute,
zone_stats_hour, alerts) ส่วน calib_jobs, calib_samples,
slot_proposals (P3) จะเพิ่มตอนถึงเฟสนั้นตามกฎห้ามข้ามเฟสใน CLAUDE.md
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"


class CameraBrand(str, enum.Enum):
    HIKVISION = "hikvision"
    DAHUA = "dahua"
    CUSTOM = "custom"


class CameraStream(str, enum.Enum):
    MAIN = "main"
    SUB = "sub"


class CameraStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MOVED = "moved"
    DISABLED = "disabled"


class SlotType(str, enum.Enum):
    NORMAL = "normal"
    DISABLED = "disabled"
    EV = "ev"
    RESERVED = "reserved"


class OccupancyState(str, enum.Enum):
    FREE = "free"
    OCCUPIED = "occupied"
    UNKNOWN = "unknown"


class LayoutStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, native_enum=False, length=20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name_th: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[str] = mapped_column(String(100))
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    expected_slots: Mapped[int] = mapped_column(Integer, default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    slots: Mapped[list["Slot"]] = relationship(back_populates="zone")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    brand: Mapped[CameraBrand] = mapped_column(SAEnum(CameraBrand, native_enum=False, length=20))
    host: Mapped[str] = mapped_column(String(100))
    port: Mapped[int] = mapped_column(Integer, default=554)
    channel: Mapped[int] = mapped_column(Integer, default=1)
    stream: Mapped[CameraStream] = mapped_column(
        SAEnum(CameraStream, native_enum=False, length=10), default=CameraStream.MAIN
    )
    rtsp_url_custom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    detect_interval_s: Mapped[int] = mapped_column(Integer, default=30)
    conf_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    tiling_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    roi_polygon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CameraStatus] = mapped_column(
        SAEnum(CameraStatus, native_enum=False, length=20), default=CameraStatus.OFFLINE
    )
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_infer_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frame_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    slots: Mapped[list["Slot"]] = relationship(back_populates="camera")


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    type: Mapped[SlotType] = mapped_column(
        SAEnum(SlotType, native_enum=False, length=20), default=SlotType.NORMAL
    )
    polygon: Mapped[list] = mapped_column(JSON)  # normalized [[x,y], ...]
    threshold: Mapped[float] = mapped_column(Float, default=0.30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    layout_status: Mapped[LayoutStatus] = mapped_column(
        SAEnum(LayoutStatus, native_enum=False, length=20), default=LayoutStatus.DRAFT
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    camera: Mapped["Camera"] = relationship(back_populates="slots")
    zone: Mapped["Zone"] = relationship(back_populates="slots")
    state: Mapped["SlotState"] = relationship(back_populates="slot", uselist=False)


class SlotState(Base):
    __tablename__ = "slot_state"

    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), primary_key=True)
    state: Mapped[OccupancyState] = mapped_column(
        SAEnum(OccupancyState, native_enum=False, length=20), default=OccupancyState.UNKNOWN
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    override_state: Mapped[OccupancyState | None] = mapped_column(
        SAEnum(OccupancyState, native_enum=False, length=20), nullable=True
    )
    override_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    override_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    override_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    slot: Mapped["Slot"] = relationship(back_populates="state")


class SlotEvent(Base):
    __tablename__ = "slot_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    from_state: Mapped[OccupancyState] = mapped_column(SAEnum(OccupancyState, native_enum=False, length=20))
    to_state: Mapped[OccupancyState] = mapped_column(SAEnum(OccupancyState, native_enum=False, length=20))
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ZoneStatMinute(Base):
    """สรุปสถานะช่องรายนาทีต่อโซน (FR-36); เก็บ 30 วันแล้วลบทิ้ง (FR-39)"""

    __tablename__ = "zone_stats_minute"

    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), primary_key=True)
    total: Mapped[int] = mapped_column(Integer)
    occupied: Mapped[int] = mapped_column(Integer)
    free: Mapped[int] = mapped_column(Integer)
    unknown: Mapped[int] = mapped_column(Integer)


class ZoneStatHour(Base):
    """สรุปรายชั่วโมงต่อโซน (FR-37); เก็บ 2 ปีแล้วลบทิ้ง (FR-39)"""

    __tablename__ = "zone_stats_hour"

    hour_ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), primary_key=True)
    avg_occ_pct: Mapped[float] = mapped_column(Float)
    max_occ_pct: Mapped[float] = mapped_column(Float)
    samples: Mapped[int] = mapped_column(Integer)


class AlertLevel(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Alert(Base):
    """แจ้งเตือนในหลังบ้าน (FR-32) เช่น กล้องหลุด/ถูกขยับ"""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[AlertLevel] = mapped_column(SAEnum(AlertLevel, native_enum=False, length=20))
    source: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
