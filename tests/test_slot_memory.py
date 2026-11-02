"""ช่องจำรถ (worker/slot_memory.py) + debounce แบบยืนยันว่างหลายรอบ"""
from datetime import datetime, timedelta

import numpy as np

from worker.occupancy import apply_debounce
from worker.slot_memory import (
    MAX_HOLD,
    decode_signature,
    encode_signature,
    is_strong_detection,
    patch_signature,
    should_hold,
    similarity,
)

SLOT = [[0.2, 0.2], [0.6, 0.2], [0.6, 0.6], [0.2, 0.6]]
NOW = datetime(2026, 11, 2, 12, 0, 0)


def _frame(seed: int, brightness: float = 1.0) -> np.ndarray:
    """ภาพสุ่มที่มีลวดลาย (seed เดิม = ฉากเดิม)"""
    rng = np.random.default_rng(seed)
    img = rng.integers(40, 200, size=(120, 160, 3)).astype(np.float32)
    return np.clip(img * brightness, 0, 255).astype(np.uint8)


def test_signature_shape_and_roundtrip():
    sig = patch_signature(_frame(1), SLOT)
    assert sig.shape == (32, 32) and sig.dtype == np.uint8
    assert np.array_equal(decode_signature(encode_signature(sig)), sig)


def test_decode_bad_text_returns_none():
    assert decode_signature(None) is None
    assert decode_signature("") is None
    assert decode_signature("YWJj") is None  # ยาวไม่ครบ


def test_same_scene_is_similar_even_when_darker():
    a = patch_signature(_frame(1), SLOT)
    b = patch_signature(_frame(1, brightness=0.7), SLOT)  # เมฆบัง แสงลดลงทั้งภาพ
    assert similarity(a, b) > 0.95


def test_different_scene_is_not_similar():
    a = patch_signature(_frame(1), SLOT)
    b = patch_signature(_frame(2), SLOT)  # รถออก ภาพช่องเปลี่ยน
    assert similarity(a, b) < 0.5


def test_flat_image_cannot_be_compared():
    flat = np.full((32, 32), 20, dtype=np.uint8)  # กลางคืนมืดสนิท
    assert similarity(flat, patch_signature(_frame(1), SLOT)) is None


def test_strong_detection_rule():
    assert is_strong_detection(0.7, 0.4)
    assert not is_strong_detection(0.5, 0.4)  # ต่ำกว่า 0.6 = อาจเป็นกรอบรถคันข้างล้นเข้ามา
    assert not is_strong_detection(0.7, 0.8)


def test_hold_when_ai_misses_but_scene_unchanged():
    stored = patch_signature(_frame(1), SLOT)
    current = patch_signature(_frame(1, 0.9), SLOT)
    assert should_hold("free", stored, current, None, NOW)


def test_no_hold_when_car_left():
    stored = patch_signature(_frame(1), SLOT)
    current = patch_signature(_frame(2), SLOT)
    assert not should_hold("free", stored, current, None, NOW)


def test_no_hold_without_memory_or_when_ai_sees_car():
    current = patch_signature(_frame(1), SLOT)
    assert not should_hold("free", None, current, None, NOW)
    assert not should_hold("occupied", current, current, None, NOW)


def test_hold_expires_after_max_hold():
    sig = patch_signature(_frame(1), SLOT)
    assert should_hold("free", sig, sig, NOW - MAX_HOLD + timedelta(minutes=1), NOW)
    assert not should_hold("free", sig, sig, NOW - MAX_HOLD - timedelta(minutes=1), NOW)


def test_debounce_free_confirm_needs_all_recent_free():
    # แบบเดิม: 2 ใน 3 ก็เปลี่ยนเป็นว่าง
    assert apply_debounce(["occupied", "free", "free"], "occupied") == "free"
    # เปิดช่องจำรถ: มีรถ → ว่าง ต้องว่างครบ 3 รอบติด
    assert apply_debounce(["occupied", "free", "free"], "occupied", free_confirm=3) == "occupied"
    assert apply_debounce(["free", "free", "free"], "occupied", free_confirm=3) == "free"
    # ว่าง → มีรถ ยังใช้ 2 ใน 3 เหมือนเดิม
    assert apply_debounce(["free", "occupied", "occupied"], "free", free_confirm=3) == "occupied"
