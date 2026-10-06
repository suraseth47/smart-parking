"""Worker loop: ดึงภาพ -> ตรวจจับ -> คำนวณ occupancy+debounce -> เขียน DB ทุก interval (FR-1, FR-6..11)"""
from __future__ import annotations

import time
from datetime import datetime

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.camera_utils import build_camera_url, snapshot_path
from core.config import PROJECT_ROOT
from core.db import SessionLocal
from core.models import Camera, CameraStatus, LayoutStatus, OccupancyState, Slot, SlotEvent, SlotState
from worker.capture import grab_frame
from worker.detector import OnnxYoloxDetector
from worker.occupancy import (
    apply_debounce,
    compute_footprint,
    compute_slot_score,
    is_occupied,
    normalize_box,
    resolve_override,
    update_raw_history,
)

TICK_SECONDS = 5  # เช็คทุก 5 วิ ว่ากล้องไหนครบรอบ detect_interval_s ของตัวเองแล้วบ้าง


def run_forever() -> None:
    """เริ่มลูปหลักของ worker (เรียกจาก `python -m worker.main`)"""
    detector = OnnxYoloxDetector(PROJECT_ROOT / "models" / "yolox_s.onnx")
    while True:
        start = time.monotonic()
        run_cycle(detector)
        elapsed = time.monotonic() - start
        time.sleep(max(0.0, TICK_SECONDS - elapsed))


def run_cycle(detector: OnnxYoloxDetector) -> None:
    """ตรวจกล้องที่เปิดใช้งานทุกตัว ประมวลผลเฉพาะตัวที่ครบรอบ interval แล้ว"""
    db = SessionLocal()
    try:
        cameras = db.scalars(select(Camera).where(Camera.enabled.is_(True))).all()
        for camera in cameras:
            if _is_due(camera):
                process_camera(db, camera, detector)
    finally:
        db.close()


def _is_due(camera: Camera) -> bool:
    if camera.last_frame_at is None:
        return True
    elapsed = (datetime.utcnow() - camera.last_frame_at).total_seconds()
    return elapsed >= camera.detect_interval_s


def process_camera(db: Session, camera: Camera, detector: OnnxYoloxDetector) -> None:
    """รอบประมวลผล 1 กล้อง: ดึงภาพ -> ตรวจจับ -> อัปเดตสถานะทุกช่อง (FR-1, FR-2, FR-6..11)"""
    camera.last_frame_at = datetime.utcnow()

    try:
        frame = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        camera.status = CameraStatus.OFFLINE
        camera.last_error = str(exc)
        _mark_camera_slots_unknown(db, camera)
        db.commit()
        return

    infer_start = time.perf_counter()
    detections = detector.detect(frame)
    camera.last_infer_ms = (time.perf_counter() - infer_start) * 1000

    frame_h, frame_w = frame.shape[:2]
    camera.frame_w = frame_w
    camera.frame_h = frame_h
    camera.status = CameraStatus.ONLINE
    camera.last_error = None

    path = snapshot_path(camera.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", frame)[1].tofile(str(path))  # FR-5: เก็บภาพล่าสุด 1 ภาพ (เขียนทับ)

    footprints = [compute_footprint(normalize_box(d.box, frame_w, frame_h)) for d in detections]

    slots = db.scalars(
        select(Slot).where(
            Slot.camera_id == camera.id,
            Slot.layout_status == LayoutStatus.PUBLISHED,
            Slot.is_active.is_(True),
        )
    ).all()

    now = datetime.utcnow()
    for slot in slots:
        _update_slot_state(db, slot, footprints, now)

    db.commit()


def _update_slot_state(db: Session, slot: Slot, footprints: list, now: datetime) -> None:
    """คำนวณ score + debounce + override แล้วอัปเดต slot_state 1 ช่อง (FR-6..11)"""
    state_row = db.get(SlotState, slot.id)
    if state_row is None:
        state_row = SlotState(slot_id=slot.id, state=OccupancyState.UNKNOWN, raw_history=[])
        db.add(state_row)

    score = compute_slot_score(slot.polygon, footprints)
    raw_state = "occupied" if is_occupied(score, slot.threshold) else "free"

    previous_state = (state_row.state or OccupancyState.UNKNOWN).value
    history = update_raw_history(state_row.raw_history or [], raw_state)
    debounced_state = apply_debounce(history, previous_state)
    final_state = resolve_override(debounced_state, state_row.override_state, state_row.override_until, now)

    if final_state != previous_state:
        db.add(
            SlotEvent(
                slot_id=slot.id,
                from_state=state_row.state or OccupancyState.UNKNOWN,
                to_state=OccupancyState(final_state),
                ts=now,
            )
        )
        state_row.since = now

    state_row.state = OccupancyState(final_state)
    state_row.score = score
    state_row.raw_history = history
    state_row.updated_at = now


def _mark_camera_slots_unknown(db: Session, camera: Camera) -> None:
    """ดึงภาพไม่ได้ -> ช่องที่ publish แล้วของกล้องนี้ทั้งหมดเป็น unknown (FR-9)"""
    slots = db.scalars(
        select(Slot).where(Slot.camera_id == camera.id, Slot.layout_status == LayoutStatus.PUBLISHED)
    ).all()
    now = datetime.utcnow()
    for slot in slots:
        state_row = db.get(SlotState, slot.id)
        if state_row is None:
            state_row = SlotState(slot_id=slot.id, raw_history=[])
            db.add(state_row)

        if state_row.state != OccupancyState.UNKNOWN:
            db.add(
                SlotEvent(
                    slot_id=slot.id,
                    from_state=state_row.state or OccupancyState.UNKNOWN,
                    to_state=OccupancyState.UNKNOWN,
                    ts=now,
                )
            )
            state_row.since = now

        state_row.state = OccupancyState.UNKNOWN
        state_row.updated_at = now


if __name__ == "__main__":
    run_forever()
