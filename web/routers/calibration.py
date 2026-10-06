"""โหมดกึ่งออโต้: สร้าง calibration job (โหมด A Observation), ดู/อนุมัติ/ปฏิเสธ/แก้มุม
proposal แล้วส่ง proposal ที่อนุมัติเข้า layout draft (FR-28, FR-29)

โหมด B (Line detection) ยังไม่ทำในเฟสนี้ตามกฎห้ามข้ามเฟสใน CLAUDE.md
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from worker.calibration.observation import cancel_calib_job

router = APIRouter(prefix="/api/admin/calib", tags=["calibration"])

MIN_DURATION_HOURS = 24  # FR-28a: ระยะเวลา 1-3 วัน
MAX_DURATION_HOURS = 72


class CreateJobIn(BaseModel):
    camera_id: int
    duration_hours: int = 48
    interval_minutes: int = 5
    hour_start: int = 0
    hour_end: int = 24


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
    """สร้าง calibration job โหมด Observation (FR-28a) — worker loop จะเก็บ footprint ให้เอง"""
    camera = db.get(Camera, data.camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

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
            detail={"job_id": job.id, "duration_hours": duration_hours},
        )
    )
    db.commit()
    db.refresh(job)
    return _to_job_out(db, job)


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
