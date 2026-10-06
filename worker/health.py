"""ตรวจกล้องถูกขยับ + จัดการ alert ในหลังบ้าน (FR-30, FR-32)"""
from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Alert, AlertLevel, Camera

MIN_MATCH_COUNT = 10  # ถ้าหาจุดสังเกตร่วมกันไม่พอ ถือว่าผิดปกติ (อาจกล้องถูกขยับ/บังมิด)
MOVED_TRANSLATION_THRESHOLD_PX = 50.0  # ภาพเลื่อนเกินนี้ (พิกเซล) ถือว่ากล้องถูกขยับ


def compute_camera_transform(reference_image: np.ndarray, current_image: np.ndarray) -> np.ndarray | None:
    """คำนวณ affine transform จากภาพอ้างอิงไปภาพปัจจุบันด้วย ORB feature matching

    ใช้ร่วมกันโดย detect_camera_moved (FR-30) และปุ่ม Re-align (FR-30 เฟส 3)
    คืน None ถ้าหาจุดสังเกตร่วมกันไม่พอ หรือคำนวณ transform ไม่ได้
    """
    orb = cv2.ORB_create(nfeatures=500)
    kp1, des1 = orb.detectAndCompute(reference_image, None)
    kp2, des2 = orb.detectAndCompute(current_image, None)

    if des1 is None or des2 is None or len(kp1) < MIN_MATCH_COUNT or len(kp2) < MIN_MATCH_COUNT:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = matcher.match(des1, des2)
    if len(matches) < MIN_MATCH_COUNT:
        return None

    matches = sorted(matches, key=lambda m: m.distance)[:100]
    src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    transform, _inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC)
    return transform


def detect_camera_moved(
    reference_image: np.ndarray,
    current_image: np.ndarray,
    threshold_px: float = MOVED_TRANSLATION_THRESHOLD_PX,
) -> bool:
    """เทียบภาพปัจจุบันกับภาพอ้างอิงด้วย ORB feature matching (FR-30)

    คืน True ถ้าน่าจะกล้องถูกขยับ: หาจุดสังเกตร่วมกันไม่พอ หรือระยะเลื่อน (translation)
    ที่ประมาณได้เกิน threshold_px
    """
    transform = compute_camera_transform(reference_image, current_image)
    if transform is None:
        return True

    translation = float(np.hypot(transform[0, 2], transform[1, 2]))
    return translation > threshold_px


def apply_transform_to_polygon(
    polygon: list[list[float]], transform: np.ndarray, frame_width: int, frame_height: int
) -> list[list[float]]:
    """ขยับ polygon (normalized 0-1) ตาม affine transform ที่คำนวณได้ (FR-30 เฟส 3 ปุ่ม Re-align)"""
    result = []
    for x_norm, y_norm in polygon:
        x_px, y_px = x_norm * frame_width, y_norm * frame_height
        new_x = transform[0, 0] * x_px + transform[0, 1] * y_px + transform[0, 2]
        new_y = transform[1, 0] * x_px + transform[1, 1] * y_px + transform[1, 2]
        result.append([new_x / frame_width, new_y / frame_height])
    return result


def is_health_check_due(camera: Camera, now: datetime, interval_minutes: int = 10) -> bool:
    """FR-30: เช็คกล้องขยับทุก 10 นาที ไม่ใช่ทุกรอบตรวจจับ"""
    if camera.last_health_check_at is None:
        return True
    return (now - camera.last_health_check_at).total_seconds() >= interval_minutes * 60


def raise_alert(db: Session, level: AlertLevel, source: str, message: str) -> None:
    """สร้าง alert ใหม่ เว้นแต่มี alert ข้อความเดิมค้างอยู่แล้ว (กันสแปม)"""
    existing = db.scalar(
        select(Alert)
        .where(Alert.source == source, Alert.resolved_at.is_(None))
        .order_by(Alert.created_at.desc())
    )
    if existing is not None:
        if existing.message == message:
            return
        existing.resolved_at = datetime.utcnow()  # สถานะเปลี่ยนไปแล้ว alert เก่าหมดความหมาย
    db.add(Alert(level=level, source=source, message=message))


def resolve_alerts(db: Session, source: str) -> None:
    """กล้อง/ระบบกลับมาปกติ -> ปิด alert ที่ค้างของ source นี้ทั้งหมด"""
    now = datetime.utcnow()
    open_alerts = db.scalars(
        select(Alert).where(Alert.source == source, Alert.resolved_at.is_(None))
    ).all()
    for alert in open_alerts:
        alert.resolved_at = now
