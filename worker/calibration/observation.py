"""โหมด A: เสนอกรอบช่องจอดจากการสังเกตรถที่จอดจริง (FR-28)

ครึ่งบนของไฟล์เป็น pure function: รับ footprint (กล่อง normalized 0-1) ที่เก็บได้
จากหลายรอบของ calibration job มาจัดกลุ่มตำแหน่งที่ซ้อนกัน คัดเฉพาะกลุ่มที่ "จอดนิ่ง"
บ่อยพอ แล้วสร้าง proposal (FR-28c, FR-28d)

ครึ่งหลังเป็นฟังก์ชันที่ยุ่งกับ DB/ไฟล์: บันทึกตัวอย่าง, ปิด job แล้วสร้าง proposals
จริงลงตาราง, และลบข้อมูลดิบของ job ที่ปิดเกิน 7 วัน (FR-29f)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import cv2
from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import CalibJob, CalibJobStatus, CalibSample, SlotProposal

BoxXYXY = tuple[float, float, float, float]

CLOSED_JOB_RETENTION_DAYS = 7  # FR-29f


def compute_iou(box_a: BoxXYXY, box_b: BoxXYXY) -> float:
    """สัดส่วนพื้นที่ซ้อนกันเทียบกับพื้นที่รวมของกล่องทั้งสอง (Intersection over Union)"""
    shape_a, shape_b = box(*box_a), box(*box_b)
    union_area = shape_a.area + shape_b.area - shape_a.intersection(shape_b).area
    if union_area == 0:
        return 0.0
    return shape_a.intersection(shape_b).area / union_area


def cluster_boxes(samples: list[list[BoxXYXY]], iou_threshold: float = 0.5) -> list[dict]:
    """จัดกลุ่ม footprint ที่ซ้อนกัน (IoU > threshold) ข้ามรอบตัวอย่างทั้งหมด (FR-28c)

    คืน list ของ {"boxes": [...], "sample_indices": {int, ...}} — เทียบกล่องใหม่
    กับกล่องตัวแทน (กล่องแรก) ของกลุ่มที่มีอยู่ แบบ greedy ตามลำดับที่พบ
    """
    clusters: list[dict] = []
    for sample_idx, boxes in enumerate(samples):
        for candidate in boxes:
            matched = None
            for cluster in clusters:
                representative = cluster["boxes"][0]
                if compute_iou(candidate, representative) > iou_threshold:
                    matched = cluster
                    break
            if matched is None:
                clusters.append({"boxes": [candidate], "sample_indices": {sample_idx}})
            else:
                matched["boxes"].append(candidate)
                matched["sample_indices"].add(sample_idx)
    return clusters


def median_box(boxes: list[BoxXYXY]) -> BoxXYXY:
    """ค่ามัธยฐานของกรอบ (แยกคำนวณทีละแกน) ใช้เป็นกรอบตัวแทนของกลุ่ม (FR-28c)"""
    xs1 = sorted(b[0] for b in boxes)
    ys1 = sorted(b[1] for b in boxes)
    xs2 = sorted(b[2] for b in boxes)
    ys2 = sorted(b[3] for b in boxes)
    mid = len(boxes) // 2

    def median(values: list[float]) -> float:
        if len(values) % 2 == 1:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2

    return (median(xs1), median(ys1), median(xs2), median(ys2))


def box_to_polygon(box_xyxy: BoxXYXY) -> list[list[float]]:
    """แปลงกล่อง xyxy เป็น polygon 4 มุม เรียง TL -> TR -> BR -> BL ให้หน่วยเดียวกับ Slot.polygon"""
    x1, y1, x2, y2 = box_xyxy
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def non_max_suppression(proposals: list[dict], iou_threshold: float = 0.5) -> list[dict]:
    """ตัด proposal ที่ทับกันเกิน (FR-28c) เก็บไว้เฉพาะตัวที่ confidence สูงกว่าในกลุ่มที่ทับกัน"""
    ordered = sorted(proposals, key=lambda p: p["confidence"], reverse=True)
    kept: list[dict] = []
    for candidate in ordered:
        overlaps_kept = any(
            compute_iou(candidate["box"], kept_item["box"]) > iou_threshold for kept_item in kept
        )
        if not overlaps_kept:
            kept.append(candidate)
    return kept


def build_proposals(
    samples: list[list[BoxXYXY]],
    min_presence_ratio: float = 0.2,
    iou_threshold: float = 0.5,
) -> list[dict]:
    """สร้าง proposals จากผลสังเกตทั้ง job (FR-28c, FR-28d)

    1. จัดกลุ่ม footprint ที่ซ้อนกัน
    2. คัดเฉพาะกลุ่มที่ปรากฏ >= min_presence_ratio ของจำนวนตัวอย่าง (ตัดรถวิ่งผ่าน)
    3. ใช้ค่ามัธยฐานของกรอบในกลุ่มเป็น polygon, confidence = สัดส่วนการปรากฏ
    4. ตัดกรอบที่ทับกันเกิน (NMS)
    5. เรียงซ้าย->ขวา บน->ล่าง

    คืน list ของ {"polygon": [[x,y], ...], "confidence": float}
    """
    total_samples = len(samples)
    if total_samples == 0:
        return []

    clusters = cluster_boxes(samples, iou_threshold=iou_threshold)

    candidates = []
    for cluster in clusters:
        presence_ratio = len(cluster["sample_indices"]) / total_samples
        if presence_ratio < min_presence_ratio:
            continue
        representative_box = median_box(cluster["boxes"])
        candidates.append({"box": representative_box, "confidence": round(presence_ratio, 4)})

    kept = non_max_suppression(candidates, iou_threshold=iou_threshold)

    def sort_key(item: dict) -> tuple[float, float]:
        x1, y1, x2, y2 = item["box"]
        return ((y1 + y2) / 2, (x1 + x2) / 2)  # บน->ล่าง ก่อน แล้วค่อยซ้าย->ขวา

    kept.sort(key=sort_key)

    return [
        {"polygon": box_to_polygon(item["box"]), "confidence": item["confidence"]} for item in kept
    ]


# ---------------------------------------------------------------------------
# ฟังก์ชันที่ยุ่งกับ DB/ไฟล์ (ไม่ pure) — เรียกจาก worker/main.py
# ---------------------------------------------------------------------------

_last_calib_pruned_date = None


def is_sample_due(job: CalibJob, last_sample_ts: datetime | None, now: datetime) -> bool:
    """ถึงเวลาเก็บตัวอย่างใหม่หรือยัง: อยู่ในช่วงเวลาที่สนใจ + ครบความถี่ที่ตั้งไว้ (FR-28a/b)"""
    hour_start = job.params.get("hour_start", 0)
    hour_end = job.params.get("hour_end", 24)
    if not (hour_start <= now.hour < hour_end):
        return False
    if last_sample_ts is None:
        return True
    interval_minutes = job.params.get("interval_minutes", 5)
    elapsed_minutes = (now - last_sample_ts).total_seconds() / 60
    return elapsed_minutes >= interval_minutes


def is_job_finished(job: CalibJob, now: datetime) -> bool:
    """ครบระยะเวลา job แล้วหรือยัง (FR-28a)"""
    return now >= job.ends_at


def record_calib_sample(db: Session, job: CalibJob, boxes: list[BoxXYXY], frame, now: datetime) -> None:
    """บันทึก footprint 1 รอบของ job (FR-28b), อัปเดต progress, และเก็บภาพพื้นหลัง
    1 ภาพช่วงรถเยอะที่สุด (FR-28b) ไว้ให้หน้า Review ใช้ซ้อน proposals
    """
    db.add(CalibSample(job_id=job.id, ts=now, boxes=[list(b) for b in boxes]))

    total_seconds = (job.ends_at - job.started_at).total_seconds()
    if total_seconds > 0:
        job.progress = min(1.0, max(0.0, (now - job.started_at).total_seconds() / total_seconds))

    if boxes:
        existing = db.scalars(select(CalibSample.boxes).where(CalibSample.job_id == job.id)).all()
        max_count_so_far = max((len(b) for b in existing), default=0)
        if len(boxes) >= max_count_so_far:
            job_dir = get_settings().data_dir / "calib" / f"job_{job.id}"
            job_dir.mkdir(parents=True, exist_ok=True)
            path = job_dir / "background.jpg"
            cv2.imencode(".jpg", frame)[1].tofile(str(path))
            job.background_image_path = str(path)


def finalize_calib_job(db: Session, job: CalibJob, now: datetime) -> None:
    """ครบเวลา job แล้ว: รัน clustering จากตัวอย่างที่เก็บไว้ สร้าง proposals แล้วปิด job (FR-28c/d)"""
    samples = db.scalars(select(CalibSample.boxes).where(CalibSample.job_id == job.id)).all()
    boxes_per_sample = [[tuple(b) for b in sample] for sample in samples]
    proposals = build_proposals(boxes_per_sample)

    for proposal in proposals:
        db.add(
            SlotProposal(
                job_id=job.id,
                camera_id=job.camera_id,
                polygon=proposal["polygon"],
                confidence=proposal["confidence"],
            )
        )

    job.status = CalibJobStatus.DONE
    job.progress = 1.0
    job.ends_at = now  # ปรับให้ตรงเวลาปิดจริง ใช้นับ retention 7 วันของข้อมูลดิบ (FR-29f)


def cancel_calib_job(job: CalibJob, now: datetime) -> None:
    """ยกเลิก job กลางทาง (ไม่ประมวลผล samples ที่มีอยู่) — ปรับ ends_at เป็นเวลาปิดจริงเพื่อนับ retention 7 วัน"""
    job.status = CalibJobStatus.CANCELLED
    job.ends_at = now


def prune_old_calib_jobs(db: Session, now: datetime) -> None:
    """ลบข้อมูลดิบ (calib_samples + ภาพพื้นหลัง) ของ job ที่ปิดไปแล้วเกิน 7 วัน (FR-29f)

    คงแถว calib_jobs และ slot_proposals ไว้ (ไม่ใช่ข้อมูลดิบ) ลบแค่ calib_samples กับไฟล์ภาพ
    """
    cutoff = now - timedelta(days=CLOSED_JOB_RETENTION_DAYS)
    closed_jobs = db.scalars(
        select(CalibJob).where(CalibJob.status != CalibJobStatus.RUNNING, CalibJob.ends_at < cutoff)
    ).all()
    for job in closed_jobs:
        db.query(CalibSample).filter(CalibSample.job_id == job.id).delete()
        if job.background_image_path:
            Path(job.background_image_path).unlink(missing_ok=True)
            job.background_image_path = None


def maybe_prune_old_calib_jobs(db: Session, now: datetime) -> None:
    """เรียกได้ทุกรอบ worker แต่จะลบข้อมูลเก่าจริงแค่วันละครั้ง"""
    global _last_calib_pruned_date
    today = now.date()
    if _last_calib_pruned_date == today:
        return
    prune_old_calib_jobs(db, now)
    _last_calib_pruned_date = today
