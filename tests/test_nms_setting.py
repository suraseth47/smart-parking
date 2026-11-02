"""เกณฑ์ NMS รายกล้อง: รถจอดชิดกันต้องไม่ถูกตัดทิ้ง"""
import numpy as np

from worker.detector import _postprocess
from worker.vehicle_boxes import analyze_vehicle_boxes


def _two_parked_cars() -> np.ndarray:
    """ผลดิบ (decoded) ของรถ 2 คันจอดชิดกัน กรอบซ้อนกัน IoU ~0.6 (cx, cy, w, h, obj, 80 คลาส)"""
    rows = np.zeros((2, 85), dtype=np.float32)
    rows[0, :5] = [100, 100, 100, 60, 0.9]
    rows[1, :5] = [125, 100, 100, 60, 0.8]
    rows[:, 5 + 2] = 1.0  # class 2 = car
    return rows


def test_default_nms_drops_neighbour_car():
    assert len(_postprocess(_two_parked_cars(), 1.0, 0.35, 0.45)) == 1


def test_higher_nms_keeps_both_cars():
    assert len(_postprocess(_two_parked_cars(), 1.0, 0.35, 0.65)) == 2


class _SpyDetector:
    def __init__(self):
        self.kwargs = None

    def detect(self, image, other_classes_min_score=None, **kwargs):
        self.kwargs = kwargs
        return []


def test_camera_nms_is_passed_to_detector():
    spy = _SpyDetector()
    analyze_vehicle_boxes(spy, np.zeros((100, 100, 3), np.uint8), nms_threshold=0.65)
    assert spy.kwargs == {"nms_threshold": 0.65}


def test_no_nms_setting_keeps_old_call():
    spy = _SpyDetector()
    analyze_vehicle_boxes(spy, np.zeros((100, 100, 3), np.uint8))
    assert spy.kwargs == {}
