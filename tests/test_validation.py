from core.validation import compute_accuracy


def _item(detected, confirmed):
    return {"detected_state": detected, "confirmed_state": confirmed}


def test_all_correct_is_100_percent():
    samples = [[_item("occupied", "occupied"), _item("free", "free")]]
    result = compute_accuracy(samples)
    assert result["accuracy_pct"] == 100.0
    assert result["total_compared"] == 2
    assert result["correct"] == 2


def test_half_correct_is_50_percent():
    samples = [[_item("occupied", "free"), _item("free", "free")]]
    result = compute_accuracy(samples)
    assert result["accuracy_pct"] == 50.0


def test_unconfirmed_items_excluded():
    samples = [[_item("occupied", "occupied"), _item("free", None)]]
    result = compute_accuracy(samples)
    assert result["total_compared"] == 1
    assert result["accuracy_pct"] == 100.0


def test_unknown_detected_state_excluded():
    samples = [[_item("unknown", "free"), _item("occupied", "occupied")]]
    result = compute_accuracy(samples)
    assert result["total_compared"] == 1
    assert result["accuracy_pct"] == 100.0


def test_no_comparable_items_returns_none_accuracy():
    samples = [[_item("unknown", "free")], [_item("occupied", None)]]
    result = compute_accuracy(samples)
    assert result["total_compared"] == 0
    assert result["accuracy_pct"] is None


def test_aggregates_across_multiple_samples():
    samples = [
        [_item("occupied", "occupied")],
        [_item("free", "occupied")],
        [_item("free", "free")],
    ]
    result = compute_accuracy(samples)
    assert result["total_compared"] == 3
    assert result["correct"] == 2
    assert result["accuracy_pct"] == round(2 / 3 * 100, 1)
