import numpy as np
import pytest

from worker.calibration.lines import (
    detect_line_segments,
    group_lines_by_angle,
    line_angle_deg,
    line_length,
    line_midpoint,
    pair_parallel_lines,
    pair_to_polygon,
    perpendicular_distance,
    propose_polygons_from_lines,
)


def _draw_parallel_vertical_lines(gap_px: int, canvas_size: int = 300) -> np.ndarray:
    """วาดเส้นขาวแนวตั้ง 2 เส้น ห่างกัน gap_px พิกเซล บนพื้นดำ (จำลองเส้นช่องจอด)"""
    frame = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8)
    import cv2

    x1 = canvas_size // 2 - gap_px // 2
    x2 = x1 + gap_px
    cv2.line(frame, (x1, 20), (x1, canvas_size - 20), (255, 255, 255), 2)
    cv2.line(frame, (x2, 20), (x2, canvas_size - 20), (255, 255, 255), 2)
    return frame


def test_line_angle_deg_horizontal_and_vertical():
    assert line_angle_deg((0, 0, 10, 0)) == pytest.approx(0.0)
    assert line_angle_deg((0, 0, 0, 10)) == pytest.approx(90.0)


def test_line_length():
    assert line_length((0, 0, 3, 4)) == pytest.approx(5.0)


def test_line_midpoint():
    assert line_midpoint((0, 0, 10, 20)) == (5.0, 10.0)


def test_group_lines_by_angle_separates_different_orientations():
    horizontal = (0, 0, 100, 0)
    vertical = (0, 0, 0, 100)
    groups = group_lines_by_angle([horizontal, vertical])
    assert len(groups) == 2


def test_group_lines_by_angle_merges_similar_orientations():
    line_a = (0, 0, 100, 0)
    line_b = (0, 50, 100, 55)  # เกือบแนวนอน ต่างกันไม่กี่องศา
    groups = group_lines_by_angle([line_a, line_b], tolerance_deg=10)
    assert len(groups) == 1


def test_perpendicular_distance_parallel_vertical_lines():
    line_a = (0, 0, 0, 100)
    line_b = (50, 0, 50, 100)
    assert perpendicular_distance(line_a, line_b) == pytest.approx(50.0)


def test_pair_parallel_lines_within_range():
    line_a = (0, 0, 0, 100)
    line_b = (50, 0, 50, 100)
    line_c = (500, 0, 500, 100)  # ไกลเกินไป ไม่น่าจะจับคู่
    pairs = pair_parallel_lines([line_a, line_b, line_c], slot_width_min=30, slot_width_max=70)
    assert pairs == [(line_a, line_b)]


def test_pair_parallel_lines_outside_range_returns_empty():
    line_a = (0, 0, 0, 100)
    line_b = (50, 0, 50, 100)
    pairs = pair_parallel_lines([line_a, line_b], slot_width_min=100, slot_width_max=200)
    assert pairs == []


def test_pair_to_polygon_normalizes_and_orders_points():
    line_a = (0, 0, 0, 100)
    line_b = (50, 0, 50, 100)
    polygon = pair_to_polygon((line_a, line_b), frame_width=100, frame_height=100)
    assert len(polygon) == 4
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    assert min(xs) == pytest.approx(0.0)
    assert max(xs) == pytest.approx(0.5)
    assert min(ys) == pytest.approx(0.0)
    assert max(ys) == pytest.approx(1.0)


def test_detect_line_segments_finds_drawn_parallel_lines():
    frame = _draw_parallel_vertical_lines(gap_px=60)
    lines = detect_line_segments(frame, min_line_length=50, hough_threshold=30)
    assert len(lines) >= 2


def test_detect_line_segments_blank_image_returns_empty():
    blank = np.zeros((300, 300, 3), dtype=np.uint8)
    assert detect_line_segments(blank) == []


def test_propose_polygons_from_lines_end_to_end():
    frame = _draw_parallel_vertical_lines(gap_px=60)
    polygons = propose_polygons_from_lines(
        frame, slot_width_min=40, slot_width_max=80, min_line_length=50, hough_threshold=30
    )
    assert len(polygons) >= 1
    # ความกว้างของ polygon ที่ได้ (normalized) ควรใกล้เคียง 60/300 = 0.2
    polygon = polygons[0]
    xs = [p[0] for p in polygon]
    width_normalized = max(xs) - min(xs)
    assert 0.15 < width_normalized < 0.25


def test_propose_polygons_from_lines_no_match_when_width_out_of_range():
    frame = _draw_parallel_vertical_lines(gap_px=60)
    polygons = propose_polygons_from_lines(
        frame, slot_width_min=200, slot_width_max=250, min_line_length=50, hough_threshold=30
    )
    assert polygons == []
