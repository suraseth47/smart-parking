"""ตารางฐานข้อมูลตาม SPEC ข้อ 6

หมายเหตุ: มีตารางของ P1 (users, zones, cameras, slots, slot_state,
slot_events, settings, audit_log), P2 (zone_stats_minute,
zone_stats_hour, alerts, validation_jobs, validation_samples —
สองตัวหลังไม่มีใน SPEC ข้อ 6 ออกแบบเพิ่มเองเพื่อรองรับ NFR-4
Validation tool) และ P3 (calib_jobs, calib_samples, slot_proposals
สำหรับโหมดกึ่งออโต้ FR-28/29)
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"        # ผู้ดูแลระบบ: ทุกอย่าง รวมถึงจัดการผู้ใช้และคำเชิญ
    OPERATOR = "operator"  # เจ้าหน้าที่: สถานะสด, กล้องวงจรปิด, แก้สถานะช่อง, รายงาน
    VIEWER = "viewer"      # ผู้ชม: สถานะสดและรายงานเท่านั้น (ดูอย่างเดียว)


class InvitationPurpose(str, enum.Enum):
    INVITE = "invite"  # เชิญผู้ใช้ใหม่ (ตั้ง username + รหัสผ่านเอง)
    RESET = "reset"    # ลิงก์ตั้งรหัสผ่านใหม่ให้ผู้ใช้เดิม


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
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # สิทธิ์รายเมนู: None = ทุกเมนูตามบทบาท, list = เฉพาะเมนูที่ติ๊ก (ดู core/permissions.py)
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Invitation(Base):
    """คำเชิญ/ลิงก์ตั้งรหัสผ่าน — เก็บเฉพาะ hash ของ token (ตัว token อยู่ในลิงก์เท่านั้น)"""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    purpose: Mapped[InvitationPurpose] = mapped_column(
        SAEnum(InvitationPurpose, native_enum=False, length=10), default=InvitationPurpose.INVITE
    )
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, native_enum=False, length=20))
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    method: Mapped[str] = mapped_column(String(10), default="link")  # "email" | "link" วิธีที่ Admin ส่ง
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)  # ข้อความถึงผู้รับ
    email_status: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "sent" | "failed" | None=ไม่ได้ส่งเอง
    email_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    # โหมด "นับวัตถุขนาดใหญ่เป็นรถ": None = ปิด, ตัวเลข = ขนาดกรอบขั้นต่ำ (สัดส่วนของพื้นที่ภาพ 0-1)
    large_object_min_area: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ROI อัตโนมัติจากช่องจอด (FR-4): None = ปิด, ตัวเลข = ขอบเผื่อรอบช่อง (สัดส่วนของภาพ 0-1)
    roi_auto_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_polygon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CameraStatus] = mapped_column(
        SAEnum(CameraStatus, native_enum=False, length=20), default=CameraStatus.OFFLINE
    )
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class ValidationJobStatus(str, enum.Enum):
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


class ValidationJob(Base):
    """สุ่มถ่ายภาพ+ตรวจจับ แล้วให้ Admin ยืนยันสถานะจริงเพื่อวัดความแม่นยำ (NFR-4)"""

    __tablename__ = "validation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    status: Mapped[ValidationJobStatus] = mapped_column(
        SAEnum(ValidationJobStatus, native_enum=False, length=20), default=ValidationJobStatus.RUNNING
    )
    target_sample_count: Mapped[int] = mapped_column(Integer, default=20)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ValidationSample(Base):
    """ภาพตัวอย่าง 1 ภาพของ validation job พร้อมผลตรวจจับ+ผลยืนยันจากคนต่อช่อง"""

    __tablename__ = "validation_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("validation_jobs.id"), index=True)
    image_path: Mapped[str] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # slot_results: [{"slot_id", "code", "polygon", "detected_state", "score", "confirmed_state"}, ...]
    # confirmed_state เป็น null จนกว่า Admin จะกดยืนยัน
    slot_results: Mapped[list] = mapped_column(JSON)


class CalibMethod(str, enum.Enum):
    OBSERVATION = "observation"
    LINES = "lines"


class CalibJobStatus(str, enum.Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CalibJob(Base):
    """งานกึ่งออโต้ของกล้องหนึ่งตัว: สังเกตรถจอดจริง (โหมด A) หรือจับเส้นช่องจอด (โหมด B) (FR-28, FR-29)"""

    __tablename__ = "calib_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    method: Mapped[CalibMethod] = mapped_column(SAEnum(CalibMethod, native_enum=False, length=20))
    # params: observation -> {duration_hours, interval_minutes, hour_start, hour_end}
    params: Mapped[dict] = mapped_column(JSON)
    status: Mapped[CalibJobStatus] = mapped_column(
        SAEnum(CalibJobStatus, native_enum=False, length=20), default=CalibJobStatus.RUNNING
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    background_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CalibSample(Base):
    """พิกัด footprint รถที่เก็บระหว่าง job กำลังทำงาน (FR-28b); ลบทิ้งหลังปิด job 7 วัน (FR-29f)"""

    __tablename__ = "calib_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("calib_jobs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    boxes: Mapped[list] = mapped_column(JSON)  # [[x1,y1,x2,y2 (normalized)], ...]


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SlotProposal(Base):
    """กรอบช่องที่ระบบเสนอจากโหมดกึ่งออโต้ รอ Admin อนุมัติ (FR-28d, FR-29d)"""

    __tablename__ = "slot_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("calib_jobs.id"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    polygon: Mapped[list] = mapped_column(JSON)  # normalized [[x,y], ...]
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[ProposalStatus] = mapped_column(
        SAEnum(ProposalStatus, native_enum=False, length=20), default=ProposalStatus.PENDING
    )
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
