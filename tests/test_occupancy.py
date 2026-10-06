from worker.occupancy import compute_footprint, compute_slot_score, is_occupied


def test_compute_footprint_returns_bottom_half():
    footprint = compute_footprint((0.0, 0.0, 10.0, 20.0))
    assert footprint == (0.0, 10.0, 10.0, 20.0)


def test_slot_score_full_overlap_is_one():
    slot = [[0, 0], [1, 0], [1, 1], [0, 1]]
    footprint = (0.0, 0.0, 1.0, 1.0)
    assert compute_slot_score(slot, [footprint]) == 1.0


def test_slot_score_no_overlap_is_zero():
    slot = [[0, 0], [1, 0], [1, 1], [0, 1]]
    footprint = (5.0, 5.0, 6.0, 6.0)
    assert compute_slot_score(slot, [footprint]) == 0.0


def test_slot_score_partial_overlap():
    slot = [[0, 0], [2, 0], [2, 2], [0, 2]]  # พื้นที่ 4
    footprint = (1.0, 0.0, 3.0, 2.0)  # ทับครึ่งหนึ่งของ slot (พื้นที่ทับ = 2)
    assert compute_slot_score(slot, [footprint]) == 0.5


def test_slot_score_uses_max_among_multiple_cars():
    slot = [[0, 0], [2, 0], [2, 2], [0, 2]]
    footprints = [
        (5.0, 5.0, 6.0, 6.0),  # ไม่ทับเลย
        (0.0, 0.0, 2.0, 2.0),  # ทับเต็ม
    ]
    assert compute_slot_score(slot, footprints) == 1.0


def test_slot_score_no_detections_is_zero():
    slot = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert compute_slot_score(slot, []) == 0.0


def test_slot_score_invalid_polygon_is_zero():
    assert compute_slot_score([[0, 0], [1, 1]], [(0.0, 0.0, 1.0, 1.0)]) == 0.0


def test_is_occupied_threshold_boundary():
    assert is_occupied(0.30, 0.30) is True
    assert is_occupied(0.29, 0.30) is False
    assert is_occupied(0.31, 0.30) is True
