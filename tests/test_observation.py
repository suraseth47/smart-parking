from datetime import datetime

import pytest

from worker.calibration.observation import (
    box_to_polygon,
    build_proposals,
    cluster_boxes,
    compute_iou,
    is_job_finished,
    is_sample_due,
    median_box,
    non_max_suppression,
)


class _FakeJob:
    """จำลองแค่ attribute ที่ is_sample_due/is_job_finished ต้องใช้ (ไม่แตะ DB จริง)"""

    def __init__(self, params, ends_at=None):
        self.params = params
        self.ends_at = ends_at


def test_compute_iou_identical_boxes():
    box_a = (0.1, 0.1, 0.3, 0.3)
    assert compute_iou(box_a, box_a) == 1.0


def test_compute_iou_no_overlap():
    assert compute_iou((0.0, 0.0, 0.1, 0.1), (0.5, 0.5, 0.6, 0.6)) == 0.0


def test_compute_iou_partial_overlap():
    iou = compute_iou((0.0, 0.0, 0.2, 0.2), (0.1, 0.1, 0.3, 0.3))
    assert 0.1 < iou < 0.2  # ทับกันบางส่วน


def test_cluster_boxes_groups_overlapping_across_samples():
    samples = [
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.11, 0.1, 0.31, 0.3)],  # ตำแหน่งเดิม ขยับเล็กน้อย
        [(0.7, 0.7, 0.9, 0.9)],  # คนละตำแหน่ง
    ]
    clusters = cluster_boxes(samples, iou_threshold=0.5)
    assert len(clusters) == 2
    sizes = sorted(len(c["boxes"]) for c in clusters)
    assert sizes == [1, 2]


def test_cluster_boxes_separates_non_overlapping():
    samples = [[(0.0, 0.0, 0.1, 0.1)], [(0.5, 0.5, 0.6, 0.6)]]
    clusters = cluster_boxes(samples)
    assert len(clusters) == 2


def test_median_box_odd_count():
    boxes = [(0.1, 0.1, 0.3, 0.3), (0.2, 0.2, 0.4, 0.4), (0.3, 0.3, 0.5, 0.5)]
    assert median_box(boxes) == (0.2, 0.2, 0.4, 0.4)


def test_median_box_even_count():
    boxes = [(0.0, 0.0, 0.2, 0.2), (0.2, 0.2, 0.4, 0.4)]
    assert median_box(boxes) == pytest.approx((0.1, 0.1, 0.3, 0.3))


def test_box_to_polygon_order_is_tl_tr_br_bl():
    polygon = box_to_polygon((0.1, 0.2, 0.3, 0.4))
    assert polygon == [[0.1, 0.2], [0.3, 0.2], [0.3, 0.4], [0.1, 0.4]]


def test_non_max_suppression_keeps_higher_confidence():
    proposals = [
        {"box": (0.1, 0.1, 0.3, 0.3), "confidence": 0.9},
        {"box": (0.12, 0.1, 0.32, 0.3), "confidence": 0.4},  # ทับกันมาก confidence ต่ำกว่า
        {"box": (0.7, 0.7, 0.9, 0.9), "confidence": 0.5},  # คนละตำแหน่ง เก็บไว้ทั้งคู่
    ]
    kept = non_max_suppression(proposals, iou_threshold=0.5)
    assert len(kept) == 2
    assert {round(c["confidence"], 1) for c in kept} == {0.9, 0.5}


def test_build_proposals_filters_by_presence_ratio():
    # จอดนิ่งตำแหน่งเดิม 4 จาก 5 รอบ (80%) ปน "รถวิ่งผ่าน" ที่โผล่แค่ 1 รอบ (20% ถ้านับรวม)
    samples = [
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.9, 0.9, 0.95, 0.95)],  # ปรากฏแค่ 1 ใน 5 รอบ = 20% พอดี เก็บไว้ตาม >= เกณฑ์
    ]
    proposals = build_proposals(samples, min_presence_ratio=0.2)
    assert len(proposals) == 2
    confidences = sorted(p["confidence"] for p in proposals)
    assert confidences == [0.2, 0.8]


def test_build_proposals_drops_passing_cars_below_threshold():
    samples = [
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.1, 0.1, 0.3, 0.3)],
        [(0.9, 0.9, 0.95, 0.95)],  # ปรากฏ 1 ใน 10 รอบ = 10% < 20% ตัดทิ้ง (รถวิ่งผ่าน)
    ]
    proposals = build_proposals(samples, min_presence_ratio=0.2)
    assert len(proposals) == 1
    assert proposals[0]["confidence"] > 0.8


def test_build_proposals_empty_samples():
    assert build_proposals([]) == []


def test_build_proposals_sorted_top_to_bottom_then_left_to_right():
    samples = [
        [
            (0.6, 0.1, 0.8, 0.3),  # บนขวา
            (0.1, 0.1, 0.3, 0.3),  # บนซ้าย
            (0.1, 0.6, 0.3, 0.8),  # ล่างซ้าย
        ]
    ] * 3
    proposals = build_proposals(samples, min_presence_ratio=0.5)
    assert len(proposals) == 3
    # บนซ้าย, บนขวา, ล่างซ้าย ตามลำดับ (บน->ล่าง ก่อน แล้วค่อยซ้าย->ขวา)
    tops = [p["polygon"][0] for p in proposals]
    assert tops[0][1] == tops[1][1] == 0.1  # แถวบนสองอันมาก่อน
    assert tops[0][0] < tops[1][0]  # ในแถวบน ซ้ายมาก่อนขวา
    assert tops[2][1] == 0.6  # แถวล่างมาสุดท้าย


def test_is_sample_due_outside_hour_window_returns_false():
    job = _FakeJob(params={"hour_start": 8, "hour_end": 18})
    now = datetime(2026, 10, 6, 20, 0)  # 20:00 อยู่นอกช่วง 08:00-18:00
    assert is_sample_due(job, None, now) is False


def test_is_sample_due_first_sample_inside_window_returns_true():
    job = _FakeJob(params={"hour_start": 8, "hour_end": 18})
    now = datetime(2026, 10, 6, 9, 0)
    assert is_sample_due(job, None, now) is True


def test_is_sample_due_respects_interval_minutes():
    job = _FakeJob(params={"interval_minutes": 5})
    now = datetime(2026, 10, 6, 12, 10)
    last_sample = datetime(2026, 10, 6, 12, 7)  # ผ่านมาแค่ 3 นาที ยังไม่ครบ 5
    assert is_sample_due(job, last_sample, now) is False

    last_sample_long_ago = datetime(2026, 10, 6, 12, 4)  # ผ่านมา 6 นาที ครบแล้ว
    assert is_sample_due(job, last_sample_long_ago, now) is True


def test_is_sample_due_default_window_is_whole_day():
    job = _FakeJob(params={})
    now = datetime(2026, 10, 6, 2, 0)  # ตีสอง แต่ไม่ได้ตั้ง hour_start/hour_end ไว้
    assert is_sample_due(job, None, now) is True


def test_is_job_finished():
    job = _FakeJob(params={}, ends_at=datetime(2026, 10, 6, 12, 0))
    assert is_job_finished(job, datetime(2026, 10, 6, 11, 59)) is False
    assert is_job_finished(job, datetime(2026, 10, 6, 12, 0)) is True
    assert is_job_finished(job, datetime(2026, 10, 6, 12, 1)) is True
