"""Worker loop: ดึงภาพ -> ตรวจจับ -> คำนวณ occupancy+debounce -> เขียน DB ทุก interval (FR-1, FR-6..11)"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.camera_state import mark_camera_slots_unknown
from core.camera_utils import build_camera_url, snapshot_path
from core.backup import backup_hour, is_backup_due, list_backups, run_backup
from core.config import get_detector_model_path, get_settings, local_utc_offset_hours
from core.db import SessionLocal
from core.models import (
    AlertLevel,
    CalibJob,
    CalibJobStatus,
    CalibMethod,
    CalibSample,
    Camera,
    CameraStatus,
    LayoutStatus,
    OccupancyState,
    Slot,
    SlotEvent,
    SlotState,
)
from worker.calibration.observation import (
    finalize_calib_job,
    is_job_finished,
    is_sample_due,
    maybe_prune_old_calib_jobs,
    record_calib_sample,
)
from worker.capture import grab_frame
from worker.detector import OnnxYoloxDetector
from worker.vehicle_boxes import camera_roi, detect_vehicle_footprints
from core.app_settings import load_health
from worker.health import detect_camera_moved, is_health_check_due, raise_alert, resolve_alerts
from worker.stats import maybe_prune_old_stats, maybe_record_minute_stats
from worker.occupancy import (
    apply_debounce,
    compute_slot_score,
    is_occupied,
    resolve_override,
    update_raw_history,
)

TICK_SECONDS = 5  # เช็คทุก 5 วิ ว่ากล้องไหนครบรอบ detect_interval_s ของตัวเองแล้วบ้าง


def run_forever() -> None:
    """เริ่มลูปหลักของ worker (เรียกจาก `python -m worker.main`)"""
    model_path = get_detector_model_path()
    print(f"[worker] ใช้โมเดล {model_path.name}", flush=True)
    detector = OnnxYoloxDetector(model_path)
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

        now = datetime.utcnow()
        maybe_record_minute_stats(db, now)  # FR-36, FR-37
        maybe_prune_old_stats(db, now)  # FR-39, FR-10
        _process_calib_jobs(db, detector, now)  # FR-28
        _maybe_backup(now)  # NFR-7: สำรองฐานข้อมูลทุกวัน (ไม่ต้องตั้ง cron บนเครื่อง host)
        maybe_prune_old_calib_jobs(db, now)  # FR-29f
        db.commit()
    finally:
        db.close()


_last_backup_check: datetime | None = None


def _maybe_backup(now: datetime) -> None:
    """ตรวจวันละไม่กี่ครั้ง (ทุก 1 นาที) ว่าถึงเวลาสำรองของวันนี้หรือยัง"""
    global _last_backup_check
    if _last_backup_check is not None and (now - _last_backup_check).total_seconds() < 60:
        return
    _last_backup_check = now
    settings = get_settings()
    backup_dir = settings.data_dir / "backups"
    local_now = now + timedelta(hours=local_utc_offset_hours())
    if is_backup_due(list_backups(backup_dir), local_now, backup_hour()):
        status = run_backup(settings.db_path, backup_dir, local_now)
        print(f"[backup] {status['message']} ({status['file']})", flush=True)


def _is_due(camera: Camera) -> bool:
    if camera.last_frame_at is None:
        return True
    elapsed = (datetime.utcnow() - camera.last_frame_at).total_seconds()
    return elapsed >= camera.detect_interval_s


def process_camera(db: Session, camera: Camera, detector: OnnxYoloxDetector) -> None:
    """รอบประมวลผล 1 กล้อง: ดึงภาพ -> ตรวจกล้องขยับ -> ตรวจจับ -> อัปเดตสถานะทุกช่อง (FR-1,2,6..11,30,32)"""
    now = datetime.utcnow()
    camera.last_frame_at = now
    connection_alert_source = f"camera:{camera.id}:connection"
    moved_alert_source = f"camera:{camera.id}:moved"

    try:
        frame = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        camera.status = CameraStatus.OFFLINE
        camera.last_error = str(exc)
        raise_alert(db, AlertLevel.ERROR, connection_alert_source, f"กล้อง {camera.name} ขาดการเชื่อมต่อ: {exc}")
        _mark_camera_slots_unknown(db, camera)
        db.commit()
        return

    camera.last_error = None
    resolve_alerts(db, connection_alert_source)
    if camera.status != CameraStatus.MOVED:
        camera.status = CameraStatus.ONLINE  # ถ้าค้างเป็น moved อยู่ ให้รอผลเช็ครอบถัดไปก่อนค่อยเปลี่ยน

    frame_h, frame_w = frame.shape[:2]
    camera.frame_w = frame_w
    camera.frame_h = frame_h

    path = snapshot_path(camera.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", frame)[1].tofile(str(path))  # FR-5: เก็บภาพล่าสุด 1 ภาพ (เขียนทับ)

    health = load_health(db)  # ตั้งได้ที่หน้า ตั้งค่าระบบ → ระบบและการแสดงผล
    if not health["moved_check_enabled"]:
        if camera.status == CameraStatus.MOVED:
            camera.status = CameraStatus.ONLINE  # ปิดการตรวจแล้ว ไม่ค้างสถานะ "ถูกขยับ"
        resolve_alerts(db, moved_alert_source)
    elif camera.reference_image_path and is_health_check_due(camera, now, health["moved_check_interval_min"]):
        camera.last_health_check_at = now
        if _check_camera_moved(camera, frame, health["moved_threshold_px"]):
            camera.status = CameraStatus.MOVED
            raise_alert(
                db, AlertLevel.WARNING, moved_alert_source,
                f"กล้อง {camera.name} อาจถูกขยับตำแหน่ง กรุณาตรวจสอบ",
            )
        else:
            camera.status = CameraStatus.ONLINE
            resolve_alerts(db, moved_alert_source)

    if camera.status == CameraStatus.MOVED:
        # ช่องของกล้องที่ถูกขยับเชื่อถือไม่ได้จนกว่าจะเช็คยืนยันว่ากลับมาปกติ (FR-9)
        _mark_camera_slots_unknown(db, camera)
        db.commit()
        return

    slots = db.scalars(
        select(Slot).where(
            Slot.camera_id == camera.id,
            Slot.layout_status == LayoutStatus.PUBLISHED,
            Slot.is_active.is_(True),
        )
    ).all()

    roi = camera_roi([slot.polygon for slot in slots], camera.roi_auto_margin)
    infer_start = time.perf_counter()
    footprints = detect_vehicle_footprints(detector, frame, camera.large_object_min_area, roi)
    camera.last_infer_ms = (time.perf_counter() - infer_start) * 1000

    for slot in slots:
        _update_slot_state(db, slot, footprints, now)

    db.commit()


def _process_calib_jobs(db: Session, detector: OnnxYoloxDetector, now: datetime) -> None:
    """เก็บ footprint สำหรับ calibration job โหมด Observation ที่กำลังรัน แล้วสร้าง
    proposals เมื่อครบเวลา (FR-28) — ดึงภาพ+ตรวจจับแยกจากรอบตรวจจับปกติของกล้อง
    เพราะความถี่ของ job (ค่าเริ่ม 5 นาที) มักห่างกว่า detect_interval_s ของกล้องมาก
    """
    jobs = db.scalars(select(CalibJob).where(CalibJob.status == CalibJobStatus.RUNNING)).all()
    for job in jobs:
        if is_job_finished(job, now):
            finalize_calib_job(db, job, now)
            continue

        if job.method != CalibMethod.OBSERVATION:
            continue  # โหมด B (เส้นช่องจอด) ไม่ได้เก็บตัวอย่างต่อเนื่องแบบนี้

        camera = db.get(Camera, job.camera_id)
        if camera is None:
            continue

        last_sample_ts = db.scalars(
            select(CalibSample.ts).where(CalibSample.job_id == job.id).order_by(CalibSample.ts.desc())
        ).first()
        if not is_sample_due(job, last_sample_ts, now):
            continue

        try:
            frame = grab_frame(build_camera_url(camera))
        except RuntimeError:
            continue  # ดึงภาพไม่ได้รอบนี้ ข้ามไปก่อน ไม่ถือเป็นความล้มเหลวของ job

        boxes = detect_vehicle_footprints(detector, frame, camera.large_object_min_area)
        record_calib_sample(db, job, boxes, frame, now)


def _check_camera_moved(camera: Camera, frame, threshold_px: float) -> bool:
    """อ่านภาพอ้างอิงแล้วเทียบกับภาพปัจจุบัน; อ่านภาพอ้างอิงไม่ได้ถือว่ายังไม่ขยับ (ข้ามรอบนี้ไปก่อน)"""
    try:
        reference = grab_frame(camera.reference_image_path)
    except RuntimeError:
        return False
    return detect_camera_moved(reference, frame, threshold_px)


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
    mark_camera_slots_unknown(db, camera)


if __name__ == "__main__":
    run_forever()
