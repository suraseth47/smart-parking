from worker.stats import compute_hour_rollup


def test_compute_hour_rollup_basic_avg_max():
    # นาทีที่ 1: 2/4 ว่าง = 50% occ, นาทีที่ 2: 4/4 = 100% occ
    samples = [(2, 4), (4, 4)]
    avg, mx, n = compute_hour_rollup(samples)
    assert avg == 75.0
    assert mx == 100.0
    assert n == 2


def test_compute_hour_rollup_skips_zero_capacity_rows():
    samples = [(0, 0), (2, 4)]
    avg, mx, n = compute_hour_rollup(samples)
    assert n == 1
    assert avg == 50.0


def test_compute_hour_rollup_no_valid_samples_returns_none():
    assert compute_hour_rollup([]) is None
    assert compute_hour_rollup([(0, 0), (0, 0)]) is None


def test_compute_hour_rollup_all_free():
    avg, mx, n = compute_hour_rollup([(0, 10)])
    assert avg == 0.0
    assert mx == 0.0
