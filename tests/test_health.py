from datetime import datetime, timedelta

import cv2
import numpy as np

from worker.capture import grab_frame
from worker.health import detect_camera_moved, is_health_check_due


def _shift_image(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(image, matrix, (w, h))


def test_same_image_is_not_moved():
    frame = grab_frame("data/samples/sample_frame.jpg")
    assert detect_camera_moved(frame, frame) is False


def test_large_shift_is_detected_as_moved():
    frame = grab_frame("data/samples/sample_frame.jpg")
    shifted = _shift_image(frame, dx=150, dy=80)
    assert detect_camera_moved(frame, shifted) is True


def test_tiny_shift_within_threshold_is_not_moved():
    frame = grab_frame("data/samples/sample_frame.jpg")
    shifted = _shift_image(frame, dx=3, dy=2)
    assert detect_camera_moved(frame, shifted, threshold_px=50.0) is False


def test_blank_image_has_no_features_counts_as_moved():
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = grab_frame("data/samples/sample_frame.jpg")
    assert detect_camera_moved(frame, blank) is True


class _FakeCamera:
    def __init__(self, last_health_check_at):
        self.last_health_check_at = last_health_check_at


def test_health_check_due_when_never_checked():
    assert is_health_check_due(_FakeCamera(None), datetime(2026, 1, 1, 12, 0)) is True


def test_health_check_not_due_within_interval():
    now = datetime(2026, 1, 1, 12, 0)
    camera = _FakeCamera(now - timedelta(minutes=5))
    assert is_health_check_due(camera, now) is False


def test_health_check_due_after_interval():
    now = datetime(2026, 1, 1, 12, 0)
    camera = _FakeCamera(now - timedelta(minutes=11))
    assert is_health_check_due(camera, now) is True
