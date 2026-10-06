from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from worker.capture import grab_frame
from worker.health import (
    apply_transform_to_polygon,
    compute_camera_transform,
    detect_camera_moved,
    is_health_check_due,
)


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


def test_compute_camera_transform_detects_translation():
    frame = grab_frame("data/samples/sample_frame.jpg")
    shifted = _shift_image(frame, dx=40, dy=25)
    transform = compute_camera_transform(frame, shifted)
    assert transform is not None
    assert transform[0, 2] == pytest.approx(40, abs=5)
    assert transform[1, 2] == pytest.approx(25, abs=5)


def test_compute_camera_transform_returns_none_for_blank_image():
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = grab_frame("data/samples/sample_frame.jpg")
    assert compute_camera_transform(frame, blank) is None


def test_apply_transform_to_polygon_identity():
    identity = np.float32([[1, 0, 0], [0, 1, 0]])
    polygon = [[0.1, 0.2], [0.3, 0.2], [0.3, 0.4], [0.1, 0.4]]
    result = apply_transform_to_polygon(polygon, identity, frame_width=100, frame_height=100)
    for (x1, y1), (x2, y2) in zip(polygon, result):
        assert x1 == pytest.approx(x2)
        assert y1 == pytest.approx(y2)


def test_apply_transform_to_polygon_pure_translation():
    # เลื่อนไป 10px ในแกน x บนภาพขนาด 100x100 -> เลื่อนไป 0.1 ใน normalized coords
    transform = np.float32([[1, 0, 10], [0, 1, 0]])
    polygon = [[0.1, 0.2], [0.3, 0.2]]
    result = apply_transform_to_polygon(polygon, transform, frame_width=100, frame_height=100)
    assert result[0][0] == pytest.approx(0.2)
    assert result[1][0] == pytest.approx(0.4)
    assert result[0][1] == pytest.approx(0.2)
