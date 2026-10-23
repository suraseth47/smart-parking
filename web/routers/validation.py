"""Validation tool: สุ่มถ่ายภาพ+ตรวจจับ แล้วให้ Admin ยืนยันสถานะจริงเพื่อวัด % ความแม่นยำ (NFR-4)"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from core.camera_utils import build_camera_url
from core.config import get_detector_model_path, get_settings
from core.db import get_db
from core.models import (
    Camera,
    LayoutStatus,
    Slot,
    ValidationJob,
    ValidationJobStatus,
    ValidationSample,
)
from core.validation import compute_accuracy
from web.deps import CurrentUser, require_admin, verify_csrf
from worker.capture import grab_frame
from worker.detector import OnnxYoloxDetector
from worker.occupancy import compute_slot_score, is_occupied
from worker.vehicle_boxes import camera_roi, detect_vehicle_footprints

router = APIRouter(prefix="/api/admin/validation", tags=["validation"])

DELAY_BETWEEN_SAMPLES_S = 1.0  # เว้นระยะสั้นๆ ให้แต่ละภาพไม่เหมือนกันเป๊ะ

_detector: OnnxYoloxDetector | None = None


def _get_detector() -> OnnxYoloxDetector:
    global _detector
    if _detector is None:
        _detector = OnnxYoloxDetector(get_detector_model_path())
    return _detector


class CreateJobIn(BaseModel):
    camera_id: int
    sample_count: int = 20


class SampleOut(BaseModel):
    id: int
    captured_at: datetime
    image_url: str
    slot_results: list[dict]


class JobOut(BaseModel):
    id: int
    camera_id: int
    status: str
    target_sample_count: int
    created_at: datetime
    completed_at: datetime | None
    samples: list[SampleOut]


class ConfirmIn(BaseModel):
    slot_id: int
    confirmed_state: str  # "free" | "occupied"


@router.post("/jobs", response_model=JobOut)
def create_job(
    data: CreateJobIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    camera = db.get(Camera, data.camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

    slots = db.scalars(
        select(Slot).where(
            Slot.camera_id == camera.id,
            Slot.layout_status == LayoutStatus.PUBLISHED,
            Slot.is_active.is_(True),
        )
    ).all()
    if not slots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "กล้องนี้ยังไม่มีช่องจอดที่ publish แล้ว")

    job = ValidationJob(
        camera_id=camera.id,
        status=ValidationJobStatus.RUNNING,
        target_sample_count=data.sample_count,
        created_by=admin.id,
    )
    db.add(job)
    db.flush()

    detector = _get_detector()
    roi = camera_roi([slot.polygon for slot in slots], camera.roi_auto_margin)
    camera_url = build_camera_url(camera)
    job_dir = get_settings().data_dir / "validation" / f"job_{job.id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    for i in range(data.sample_count):
        try:
            frame = grab_frame(camera_url)
        except RuntimeError as exc:
            if i == 0:
                db.delete(job)
                db.commit()
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพจากกล้องไม่สำเร็จ: {exc}")
            break  # ถ่ายได้บ้างแล้ว เก็บผลเท่าที่มีไว้ก่อน

        footprints = detect_vehicle_footprints(detector, frame, camera.large_object_min_area, roi)

        slot_results = []
        for slot in slots:
            score = compute_slot_score(slot.polygon, footprints)
            detected_state = "occupied" if is_occupied(score, slot.threshold) else "free"
            slot_results.append(
                {
                    "slot_id": slot.id,
                    "code": slot.code,
                    "polygon": slot.polygon,
                    "detected_state": detected_state,
                    "score": round(score, 3),
                    "confirmed_state": None,
                }
            )

        sample = ValidationSample(job_id=job.id, slot_results=slot_results, image_path="")
        db.add(sample)
        db.flush()

        image_path = job_dir / f"sample_{sample.id}.jpg"
        cv2.imencode(".jpg", frame)[1].tofile(str(image_path))
        sample.image_path = str(image_path)
        db.commit()

        if i < data.sample_count - 1:
            time.sleep(DELAY_BETWEEN_SAMPLES_S)

    job.status = ValidationJobStatus.DONE
    job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    return _job_to_out(db, job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    jobs = db.scalars(select(ValidationJob).order_by(ValidationJob.created_at.desc())).all()
    return [_job_to_out(db, job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    job = db.get(ValidationJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ job นี้")
    return _job_to_out(db, job)


@router.get("/jobs/{job_id}/samples/{sample_id}/image")
def get_sample_image(
    job_id: int,
    sample_id: int,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    sample = _get_sample_or_404(db, job_id, sample_id)
    return FileResponse(sample.image_path)


@router.post("/jobs/{job_id}/samples/{sample_id}/confirm")
def confirm_sample_slot(
    job_id: int,
    sample_id: int,
    data: ConfirmIn,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    if data.confirmed_state not in {"free", "occupied"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirmed_state ต้องเป็น free หรือ occupied")

    sample = _get_sample_or_404(db, job_id, sample_id)
    slot_results = sample.slot_results
    match = next((r for r in slot_results if r["slot_id"] == data.slot_id), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบช่องนี้ในภาพตัวอย่างนี้")

    match["confirmed_state"] = data.confirmed_state
    # แค่ reassign ไม่พอ: SQLAlchemy ไม่เห็นว่า JSON เปลี่ยนถ้าเป็น list object เดิม ต้องบอกตรงๆ
    flag_modified(sample, "slot_results")
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    job = db.get(ValidationJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ job นี้")
    samples = db.scalars(select(ValidationSample).where(ValidationSample.job_id == job_id)).all()
    return compute_accuracy([s.slot_results for s in samples])


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    job = db.get(ValidationJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ job นี้")
    samples = db.scalars(select(ValidationSample).where(ValidationSample.job_id == job_id)).all()
    for sample in samples:
        _delete_file_quietly(sample.image_path)
        db.delete(sample)
    db.flush()  # ลบ samples ให้เสร็จก่อน กัน FK constraint ตอนลบ job (ไม่มี relationship() ให้ SQLAlchemy เรียงลำดับเอง)
    db.delete(job)
    db.commit()


def _job_to_out(db: Session, job: ValidationJob) -> dict:
    samples = db.scalars(
        select(ValidationSample).where(ValidationSample.job_id == job.id).order_by(ValidationSample.id)
    ).all()
    return {
        "id": job.id,
        "camera_id": job.camera_id,
        "status": job.status.value,
        "target_sample_count": job.target_sample_count,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "samples": [
            {
                "id": s.id,
                "captured_at": s.captured_at,
                "image_url": f"/api/admin/validation/jobs/{job.id}/samples/{s.id}/image",
                "slot_results": s.slot_results,
            }
            for s in samples
        ],
    }


def _get_sample_or_404(db: Session, job_id: int, sample_id: int) -> ValidationSample:
    sample = db.get(ValidationSample, sample_id)
    if sample is None or sample.job_id != job_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบภาพตัวอย่างนี้")
    return sample


def _delete_file_quietly(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
