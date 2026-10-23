"""ROI อัตโนมัติจากช่องจอด (FR-4): คำนวณกรอบ, ตัดภาพ, แปลงกรอบกลับเป็นพิกัดภาพเต็ม"""
from dataclasses import dataclass

import numpy as np

from worker.roi import compute_roi, roi_to_pixels, shift_box
from worker.vehicle_boxes import analyze_vehicle_boxes, camera_roi, effective_roi

SLOT_LEFT = [[0.40, 0.50], [0.50, 0.50], [0.50, 0.80], [0.40, 0.80]]
SLOT_RIGHT = [[0.55, 0.50], [0.65, 0.50], [0.65, 0.80], [0.55, 0.80]]


def _approx(a, b):
    return all(abs(x - y) < 1e-9 for x, y in zip(a, b))


def test_compute_roi_covers_all_slots_plus_margin():
    assert _approx(compute_roi([SLOT_LEFT, SLOT_RIGHT], 0.1), (0.30, 0.40, 0.75, 0.90))


def test_compute_roi_clips_to_frame():
    assert _approx(compute_roi([SLOT_LEFT], 0.6), (0.0, 0.0, 1.0, 1.0))


def test_compute_roi_without_slots_is_none():
    assert compute_roi([], 0.1) is None


def test_camera_roi_off_when_margin_is_none():
    assert camera_roi([SLOT_LEFT], None) is None


def test_roi_to_pixels_skips_tiny_and_full_frame():
    assert roi_to_pixels((0.5, 0.5, 0.51, 0.51), 1920, 1080) is None  # เล็กเกิน
    assert roi_to_pixels((0.0, 0.0, 1.0, 1.0), 1920, 1080) is None   # เต็มภาพ ไม่ต้องตัด
    assert roi_to_pixels((0.25, 0.5, 0.75, 1.0), 2000, 1000) == (500, 500, 1500, 1000)


def test_shift_box_moves_back_to_full_frame():
    assert shift_box((10, 20, 30, 40), 500, 100) == (510, 120, 530, 140)


@dataclass
class FakeDetection:
    box: tuple
    score: float
    class_name: str


class RecordingDetector:
    """จำขนาดภาพที่ได้รับ และคืนรถ 1 คันที่มุมซ้ายบนของภาพที่ได้รับ (พิกัดภาพที่ตัดแล้ว)"""

    def __init__(self):
        self.seen_shape = None

    def detect(self, image, other_classes_min_score=None):
        self.seen_shape = image.shape
        return [FakeDetection((0, 0, 100, 50), 0.9, "car")]


def test_analyze_crops_frame_and_maps_boxes_back():
    frame = np.zeros((1000, 2000, 3), np.uint8)
    detector = RecordingDetector()
    roi = (0.25, 0.5, 0.75, 1.0)  # = พิกเซล (500, 500) ถึง (1500, 1000)
    boxes = analyze_vehicle_boxes(detector, frame, None, roi)
    assert detector.seen_shape[:2] == (500, 1000)  # AI ได้ภาพที่ตัดแล้ว
    # รถที่ (0,0)-(100,50) ในภาพตัด = (500,500)-(600,550) ในภาพเต็ม
    assert _approx(boxes[0].box, (0.25, 0.5, 0.30, 0.55))


def test_analyze_without_roi_uses_full_frame():
    frame = np.zeros((1000, 2000, 3), np.uint8)
    detector = RecordingDetector()
    boxes = analyze_vehicle_boxes(detector, frame, None, None)
    assert detector.seen_shape[:2] == (1000, 2000)
    assert _approx(boxes[0].box, (0.0, 0.0, 0.05, 0.05))


def test_effective_roi_reports_what_was_cropped():
    frame = np.zeros((1000, 2000, 3), np.uint8)
    assert _approx(effective_roi((0.25, 0.5, 0.75, 1.0), frame), (0.25, 0.5, 0.75, 1.0))
    assert effective_roi((0.0, 0.0, 1.0, 1.0), frame) is None
    assert effective_roi(None, frame) is None
