from datetime import datetime, timedelta

from worker.occupancy import (
    apply_debounce,
    compute_footprint,
    compute_slot_score,
    is_occupied,
    normalize_box,
    resolve_override,
    update_raw_history,
)


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


def test_normalize_box():
    box = normalize_box((100.0, 200.0, 300.0, 400.0), frame_width=1000, frame_height=500)
    assert box == (0.1, 0.4, 0.3, 0.8)


# ---------- update_raw_history (FR-8) ----------

def test_update_raw_history_appends():
    assert update_raw_history([], "free") == ["free"]
    assert update_raw_history(["free"], "occupied") == ["free", "occupied"]


def test_update_raw_history_keeps_last_3_only():
    history = update_raw_history(["free", "free", "occupied"], "occupied")
    assert history == ["free", "occupied", "occupied"]


# ---------- apply_debounce (FR-8) ----------

def test_debounce_empty_history_keeps_current_state():
    assert apply_debounce([], "free") == "free"


def test_debounce_2_of_3_majority_switches_state():
    assert apply_debounce(["occupied", "occupied", "free"], "free") == "occupied"


def test_debounce_3_of_3_switches_state():
    assert apply_debounce(["occupied", "occupied", "occupied"], "free") == "occupied"


def test_debounce_tie_keeps_current_state():
    assert apply_debounce(["occupied", "free"], "free") == "free"
    assert apply_debounce(["occupied", "free"], "occupied") == "occupied"


def test_debounce_majority_matches_current_state_is_noop():
    assert apply_debounce(["free", "free", "occupied"], "free") == "free"


# ---------- resolve_override (FR-11) ----------

def test_override_none_uses_debounced_state():
    now = datetime(2026, 1, 1, 12, 0)
    assert resolve_override("occupied", None, None, now) == "occupied"


def test_override_active_without_expiry_wins():
    now = datetime(2026, 1, 1, 12, 0)
    assert resolve_override("free", "occupied", None, now) == "occupied"


def test_override_active_before_expiry_wins():
    now = datetime(2026, 1, 1, 12, 0)
    until = now + timedelta(minutes=10)
    assert resolve_override("free", "occupied", until, now) == "occupied"


def test_override_expired_falls_back_to_debounced_state():
    now = datetime(2026, 1, 1, 12, 0)
    until = now - timedelta(minutes=1)
    assert resolve_override("free", "occupied", until, now) == "free"
