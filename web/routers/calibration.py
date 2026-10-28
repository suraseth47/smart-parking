"""โหมดกึ่งออโต้: สร้าง calibration job (โหมด A Observation หรือ โหมด B Line detection),
ดู/อนุมัติ/ปฏิเสธ/แก้มุม proposal แล้วส่ง proposal ที่อนุมัติเข้า layout draft (FR-28, FR-29)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.camera_utils import build_camera_url, snapshot_path
from web.routers.slots import _validate_codes_unique_in_site, _validate_same_site
from core.config import get_settings
from core.models import (
    AuditLog,
    CalibJob,
    CalibJobStatus,
    CalibMethod,
    Camera,
    LayoutStatus,
    ProposalStatus,
    Slot,
    SlotProposal,
    SlotType,
    Zone,
)
from core.db import get_db
from web.deps import CurrentUser, require_admin, verify_csrf
from worker.calibration.lines import (
    DEFAULT_HOUGH_THRESHOLD,
    DEFAULT_MIN_LINE_LENGTH,
    propose_polygons_from_lines,
)
from worker.calibration.observation import cancel_calib_job
from worker.capture import grab_frame

router = APIRouter(prefix="/api/admin/calib", tags=["calibration"])

MIN_DURATION_HOURS = 24  # FR-28a: ระยะเวลา 1-3 วัน
MAX_DURATION_HOURS = 72

DEFAULT_SLOT_WIDTH_MIN = 50.0
DEFAULT_SLOT_WIDTH_MAX = 150.0


class CreateJobIn(BaseModel):
    camera_id: int
    method: CalibMethod = CalibMethod.OBSERVATION
    # โหมด Observation (FR-28a)
    duration_hours: int = 48
    interval_minutes: int = 5
    hour_start: int = 0
    hour_end: int = 24
    # โหมด Lines (FR-29a/b/c)
    slot_width_min: float = DEFAULT_SLOT_WIDTH_MIN
    slot_width_max: float = DEFAULT_SLOT_WIDTH_MAX
    min_line_length: float = DEFAULT_MIN_LINE_LENGTH
    hough_threshold: int = DEFAULT_HOUGH_THRESHOLD


class LinesPreviewIn(BaseModel):
    camera_id: int
    slot_width_min: float = DEFAULT_SLOT_WIDTH_MIN
    slot_width_max: float = DEFAULT_SLOT_WIDTH_MAX
    min_line_length: float = DEFAULT_MIN_LINE_LENGTH
    hough_threshold: int = DEFAULT_HOUGH_THRESHOLD


class LinesPreviewOut(BaseModel):
    polygons: list[list[list[float]]]
    snapshot_url: str


class JobOut(BaseModel):
    id: int
    camera_id: int
    method: CalibMethod
    status: CalibJobStatus
    progress: float
    params: dict
    started_at: datetime
    ends_at: datetime
    background_image_url: str | None
    proposal_count: int


class ProposalOut(BaseModel):
    id: int
    job_id: int
    camera_id: int
    polygon: list[list[float]]
    confidence: float
    status: ProposalStatus
    decided_at: datetime | None

    model_config = {"from_attributes": True}


class AcceptProposalIn(BaseModel):
    code: str
    zone_id: int
    type: SlotType = SlotType.NORMAL
    threshold: float = 0.30


class PatchProposalIn(BaseModel):
    polygon: list[list[float]]


@router.post("/jobs", response_model=JobOut)
def create_job(
    data: CreateJobIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """สร้าง calibration job — โหมด Observation (FR-28a, รัน background ต่อ) หรือ
    โหมด Lines (FR-29a/b, ประมวลผลจบทันทีจากภาพปัจจุบันของกล้อง)
    """
    camera = db.get(Camera, data.camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

    if data.method == CalibMethod.LINES:
        return _create_lines_job(db, camera, data, admin)
    return _create_observation_job(db, camera, data, admin)


def _create_observation_job(db: Session, camera: Camera, data: CreateJobIn, admin: CurrentUser) -> JobOut:
    duration_hours = max(MIN_DURATION_HOURS, min(MAX_DURATION_HOURS, data.duration_hours))
    if not (0 <= data.hour_start < data.hour_end <= 24):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ช่วงเวลาที่สนใจไม่ถูกต้อง (0 <= hour_start < hour_end <= 24)")

    now = datetime.utcnow()
    job = CalibJob(
        camera_id=camera.id,
        method=CalibMethod.OBSERVATION,
        params={
            "interval_minutes": max(1, data.interval_minutes),
            "hour_start": data.hour_start,
            "hour_end": data.hour_end,
        },
        status=CalibJobStatus.RUNNING,
        started_at=now,
        ends_at=now + timedelta(hours=duration_hours),
        created_by=admin.id,
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            user_id=admin.id,
            action="create_calib_job",
            target=f"camera:{camera.id}",
            detail={"job_id": job.id, "method": "observation", "duration_hours": duration_hours},
        )
    )
    db.commit()
    db.refresh(job)
    return _to_job_out(db, job)


def _create_lines_job(db: Session, camera: Camera, data: CreateJobIn, admin: CurrentUser) -> JobOut:
    try:
        frame = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพจากกล้องไม่สำเร็จ: {exc}")

    polygons = propose_polygons_from_lines(
        frame,
        slot_width_min=data.slot_width_min,
        slot_width_max=data.slot_width_max,
        min_line_length=data.min_line_length,
        hough_threshold=data.hough_threshold,
    )

    now = datetime.utcnow()
    job_dir = get_settings().data_dir / "calib"
    job = CalibJob(
        camera_id=camera.id,
        method=CalibMethod.LINES,
        params={
            "slot_width_min": data.slot_width_min,
            "slot_width_max": data.slot_width_max,
            "min_line_length": data.min_line_length,
            "hough_threshold": data.hough_threshold,
        },
        status=CalibJobStatus.DONE,
        progress=1.0,
        started_at=now,
        ends_at=now,
        created_by=admin.id,
    )
    db.add(job)
    db.flush()

    image_dir = job_dir / f"job_{job.id}"
    image_dir.mkdir(parents=True, exist_ok=True)
    background_path = image_dir / "background.jpg"
    cv2.imencode(".jpg", frame)[1].tofile(str(background_path))
    job.background_image_path = str(background_path)

    for polygon in polygons:
        db.add(SlotProposal(job_id=job.id, camera_id=camera.id, polygon=polygon, confidence=1.0))

    db.add(
        AuditLog(
            user_id=admin.id,
            action="create_calib_job",
            target=f"camera:{camera.id}",
            detail={"job_id": job.id, "method": "lines", "proposal_count": len(polygons)},
        )
    )
    db.commit()
    db.refresh(job)
    return _to_job_out(db, job)


@router.post("/lines/preview", response_model=LinesPreviewOut)
def preview_lines(
    data: LinesPreviewIn,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    """ปรับพารามิเตอร์ดูผลสด ไม่บันทึกอะไรลง DB (FR-29c)"""
    camera = db.get(Camera, data.camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

    try:
        frame = grab_frame(build_camera_url(camera))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ดึงภาพจากกล้องไม่สำเร็จ: {exc}")

    polygons = propose_polygons_from_lines(
        frame,
        slot_width_min=data.slot_width_min,
        slot_width_max=data.slot_width_max,
        min_line_length=data.min_line_length,
        hough_threshold=data.hough_threshold,
    )

    path = snapshot_path(camera.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", frame)[1].tofile(str(path))

    return LinesPreviewOut(polygons=polygons, snapshot_url=f"/api/admin/cameras/{camera.id}/snapshot")


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    jobs = db.scalars(select(CalibJob).order_by(CalibJob.started_at.desc())).all()
    return [_to_job_out(db, job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    job = _get_job_or_404(db, job_id)
    return _to_job_out(db, job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """ยกเลิก job กลางทาง (FR-28a) — ไม่ประมวลผล samples ที่เก็บมาแล้ว"""
    job = _get_job_or_404(db, job_id)
    if job.status != CalibJobStatus.RUNNING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "job นี้ไม่ได้กำลังทำงานอยู่")

    cancel_calib_job(job, datetime.utcnow())
    db.add(AuditLog(user_id=admin.id, action="cancel_calib_job", target=f"calib_job:{job.id}"))
    db.commit()
    db.refresh(job)
    return _to_job_out(db, job)


@router.get("/jobs/{job_id}/background")
def get_job_background(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    job = _get_job_or_404(db, job_id)
    if not job.background_image_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job นี้ยังไม่มีภาพพื้นหลัง")
    return FileResponse(job.background_image_path)


@router.get("/jobs/{job_id}/proposals", response_model=list[ProposalOut])
def list_proposals(job_id: int, db: Session = Depends(get_db), _admin: CurrentUser = Depends(require_admin)):
    _get_job_or_404(db, job_id)
    return db.scalars(
        select(SlotProposal).where(SlotProposal.job_id == job_id).order_by(SlotProposal.id)
    ).all()


@router.patch("/proposals/{proposal_id}", response_model=ProposalOut)
def patch_proposal(
    proposal_id: int,
    data: PatchProposalIn,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """แก้มุมกรอบก่อนอนุมัติ (FR-29d)"""
    proposal = _get_proposal_or_404(db, proposal_id)
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposal นี้ตัดสินใจไปแล้ว แก้ไม่ได้")
    proposal.polygon = data.polygon
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept_proposal(
    proposal_id: int,
    data: AcceptProposalIn,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    """อนุมัติ proposal -> สร้างช่องจอดใหม่เป็น draft (FR-29e) ต้อง Preview+Publish ต่อเองในหน้า Layout editor"""
    proposal = _get_proposal_or_404(db, proposal_id)
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposal นี้ตัดสินใจไปแล้ว")
    if db.get(Zone, data.zone_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ไม่พบโซน id={data.zone_id}")
    camera = db.get(Camera, proposal.camera_id)
    if camera is not None:
        # ใช้กฎเดียวกับหน้าวาดผัง: โซนต้องอยู่สถานที่เดียวกับกล้อง และรหัสช่องห้ามซ้ำในสถานที่ (TOR 4.6)
        candidate = SimpleNamespace(code=data.code, zone_id=data.zone_id)
        existing = db.scalars(select(Slot).where(Slot.camera_id == camera.id)).all()
        _validate_same_site(db, camera, [candidate])
        _validate_codes_unique_in_site(db, camera, [candidate, *existing])

    slot = Slot(
        camera_id=proposal.camera_id,
        code=data.code,
        zone_id=data.zone_id,
        type=data.type,
        polygon=proposal.polygon,
        threshold=data.threshold,
        layout_status=LayoutStatus.DRAFT,
    )
    db.add(slot)

    now = datetime.utcnow()
    proposal.status = ProposalStatus.ACCEPTED
    proposal.decided_by = admin.id
    proposal.decided_at = now

    db.add(
        AuditLog(
            user_id=admin.id,
            action="accept_proposal",
            target=f"slot_proposal:{proposal.id}",
            detail={"code": data.code, "zone_id": data.zone_id},
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "มีรหัสช่องซ้ำกับช่องจอดอื่นในระบบ")

    db.refresh(proposal)
    return proposal


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
    _csrf: None = Depends(verify_csrf),
):
    proposal = _get_proposal_or_404(db, proposal_id)
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "proposal นี้ตัดสินใจไปแล้ว")

    proposal.status = ProposalStatus.REJECTED
    proposal.decided_by = admin.id
    proposal.decided_at = datetime.utcnow()
    db.add(AuditLog(user_id=admin.id, action="reject_proposal", target=f"slot_proposal:{proposal.id}"))
    db.commit()
    db.refresh(proposal)
    return proposal


def _to_job_out(db: Session, job: CalibJob) -> JobOut:
    count = len(db.scalars(select(SlotProposal.id).where(SlotProposal.job_id == job.id)).all())
    return JobOut(
        id=job.id,
        camera_id=job.camera_id,
        method=job.method,
        status=job.status,
        progress=job.progress,
        params=job.params,
        started_at=job.started_at,
        ends_at=job.ends_at,
        background_image_url=f"/api/admin/calib/jobs/{job.id}/background" if job.background_image_path else None,
        proposal_count=count,
    )


def _get_job_or_404(db: Session, job_id: int) -> CalibJob:
    job = db.get(CalibJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ job นี้")
    return job


def _get_proposal_or_404(db: Session, proposal_id: int) -> SlotProposal:
    proposal = db.get(SlotProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ proposal นี้")
    return proposal
