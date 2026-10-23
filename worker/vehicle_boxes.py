"""ตรวจจับรถจากภาพ 1 เฟรม แล้วคืน footprint ที่ใช้คำนวณ score ของช่องจอด

รวมไว้ที่เดียวเพื่อให้ worker, หน้า Preview (กำหนดช่องจอด), Validation และ calibration
ใช้กติกาเดียวกันเสมอ — รวมถึงโหมด "นับวัตถุขนาดใหญ่เป็นรถ" ที่ตั้งรายกล้อง
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from worker.detector import Detector
from worker.occupancy import BoxXYXY, classify_detection, compute_footprint, normalize_box

# เกณฑ์ความมั่นใจขั้นต่ำของวัตถุคลาสอื่นในโหมดวัตถุขนาดใหญ่ (ต่ำกว่าเกณฑ์รถปกติ 0.35
# เพราะโมเดลมักไม่มั่นใจในชื่อที่ทายผิด แต่กรอบยังแม่น — กันของจริงขนาดเล็กด้วยเกณฑ์ขนาดแทน)
LARGE_OBJECT_MIN_SCORE = 0.2


@dataclass
class VehicleBox:
    """กรอบ 1 กรอบที่ระบบนับเป็นรถ (พิกัด normalized 0-1)"""

    box: BoxXYXY
    footprint: BoxXYXY  # ส่วนที่ใช้คำนวณ score จริง (ครึ่งล่างของกรอบ)
    class_name: str
    score: float
    kind: str  # "vehicle" = AI ทายว่าเป็นรถ, "large" = วัตถุใหญ่ที่นับเป็นรถ


def analyze_vehicle_boxes(
    detector: Detector, frame: np.ndarray, large_object_min_area: float | None = None
) -> list[VehicleBox]:
    """ตรวจจับ -> คัดกรอบที่นับเป็นรถ พร้อมบอกชนิดและ footprint (ใช้แสดงผลใน Preview ได้ด้วย)"""
    frame_h, frame_w = frame.shape[:2]
    other_min_score = LARGE_OBJECT_MIN_SCORE if large_object_min_area is not None else None
    detections = detector.detect(frame, other_classes_min_score=other_min_score)

    result: list[VehicleBox] = []
    for detection in detections:
        normalized = normalize_box(detection.box, frame_w, frame_h)
        kind = classify_detection(detection.class_name, normalized, large_object_min_area)
        if kind:
            result.append(
                VehicleBox(normalized, compute_footprint(normalized), detection.class_name, detection.score, kind)
            )
    return result


def detect_vehicle_footprints(
    detector: Detector, frame: np.ndarray, large_object_min_area: float | None = None
) -> list[BoxXYXY]:
    """ตรวจจับ -> เลือกกรอบที่เป็นรถ -> แปลงเป็น footprint (ครึ่งล่างของกรอบ, normalized)"""
    return [v.footprint for v in analyze_vehicle_boxes(detector, frame, large_object_min_area)]
