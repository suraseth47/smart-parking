"""ตรวจจับรถจากภาพ 1 เฟรม แล้วคืน footprint ที่ใช้คำนวณ score ของช่องจอด

รวมไว้ที่เดียวเพื่อให้ worker, หน้า Preview (กำหนดช่องจอด), Validation และ calibration
ใช้กติกาเดียวกันเสมอ — รวมถึงโหมด "นับวัตถุขนาดใหญ่เป็นรถ" ที่ตั้งรายกล้อง
"""
from __future__ import annotations

import numpy as np

from worker.detector import Detector
from worker.occupancy import BoxXYXY, compute_footprint, select_vehicle_boxes

# เกณฑ์ความมั่นใจขั้นต่ำของวัตถุคลาสอื่นในโหมดวัตถุขนาดใหญ่ (ต่ำกว่าเกณฑ์รถปกติ 0.35
# เพราะโมเดลมักไม่มั่นใจในชื่อที่ทายผิด แต่กรอบยังแม่น — กันของจริงขนาดเล็กด้วยเกณฑ์ขนาดแทน)
LARGE_OBJECT_MIN_SCORE = 0.2


def detect_vehicle_footprints(
    detector: Detector, frame: np.ndarray, large_object_min_area: float | None = None
) -> list[BoxXYXY]:
    """ตรวจจับ -> เลือกกรอบที่เป็นรถ -> แปลงเป็น footprint (ครึ่งล่างของกรอบ, normalized)"""
    frame_h, frame_w = frame.shape[:2]
    other_min_score = LARGE_OBJECT_MIN_SCORE if large_object_min_area is not None else None
    detections = detector.detect(frame, other_classes_min_score=other_min_score)
    boxes = select_vehicle_boxes(detections, frame_w, frame_h, large_object_min_area)
    return [compute_footprint(box) for box in boxes]
