"""ช่องจำรถ (slot memory) — pure function ไม่ยุ่งกับ DB

ปัญหา: รถจอดนิ่งอยู่จริง แต่บางรอบ AI หากรอบรถไม่เจอ (รถจอดชิดกัน / ไกลกล้อง / ฝนตก)
ทำให้ช่องกระพริบเป็น "ว่าง"

วิธี: ทุกรอบที่ AI เห็นรถในช่องชัดเจน (score สูง) ให้จำ "ภาพย่อของช่อง" ไว้
รอบต่อไปถ้า AI บอกว่าว่าง แต่ภาพของช่องยังเหมือนตอนที่มีรถ = รถคันเดิมยังจอดอยู่ → คงสถานะมีรถ
ถ้ารถออกจริง ภาพของช่องจะเปลี่ยนชัดเจน (เห็นพื้น / เส้นช่อง) จึงปล่อยเป็นว่างตามผล AI

ภาพย่อ = ภาพขาวดำ 32x32 เฉพาะในรูปหลายเหลี่ยมของช่อง เทียบด้วย normalized cross-correlation
(ทนต่อแสงสว่าง/มืดลงทั้งภาพ เช่น เมฆบัง หรือเปิดไฟ) — ไม่ต้องใช้ AI เพิ่ม ใช้ CPU น้อยมาก
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta

import cv2
import numpy as np

SIG_SIZE = 32  # ขนาดภาพย่อของช่อง (พิกเซล)
# ภาพที่เรียบเกินไป (มืดสนิท / สีเดียวทั้งช่อง) เทียบความเหมือนไม่ได้ — ไม่จำ ไม่คงสถานะ
MIN_TEXTURE_STD = 6.0
DEFAULT_MIN_SIMILARITY = 0.75  # ความเหมือนขั้นต่ำ (-1..1) ที่ถือว่า "ภาพช่องยังเหมือนเดิม"
STRONG_SCORE = 0.6  # จำภาพช่องเฉพาะรอบที่ AI เห็นรถชัด (score >= ค่านี้และ >= เกณฑ์ของช่อง)
MAX_HOLD = timedelta(hours=24)  # คงสถานะด้วยความจำได้นานสุด กันค้าง "มีรถ" ตลอดไป
FREE_CONFIRM_ROUNDS = 3  # มีรถ → ว่าง ต้องได้ผลว่างติดกันกี่รอบ (เมื่อเปิดช่องจำรถ)


def patch_signature(frame: np.ndarray, polygon: list[list[float]]) -> np.ndarray | None:
    """ภาพย่อขาวดำ SIG_SIZE x SIG_SIZE ของช่อง (polygon เป็น normalized 0-1) — None ถ้าตัดภาพไม่ได้"""
    if frame is None or len(polygon) < 3:
        return None
    frame_h, frame_w = frame.shape[:2]
    points = np.array([[x * frame_w, y * frame_h] for x, y in polygon], dtype=np.float32)
    x, y, w, h = cv2.boundingRect(points.astype(np.int32))
    x, y = max(0, x), max(0, y)
    w, h = min(w, frame_w - x), min(h, frame_h - y)
    if w < 4 or h < 4:
        return None

    crop = frame[y:y + h, x:x + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(points - [x, y]).astype(np.int32)], 255)
    inside = gray[mask > 0]
    if inside.size == 0:
        return None
    # นอกรูปหลายเหลี่ยมเติมด้วยค่าเฉลี่ย เพื่อไม่ให้ช่องข้างๆ มีผลต่อการเทียบ
    filled = np.where(mask > 0, gray, np.uint8(inside.mean()))
    return cv2.resize(filled, (SIG_SIZE, SIG_SIZE), interpolation=cv2.INTER_AREA)


def encode_signature(signature: np.ndarray) -> str:
    """เก็บลง DB เป็นข้อความ (base64 ของพิกเซล uint8)"""
    return base64.b64encode(signature.astype(np.uint8).tobytes()).decode("ascii")


def decode_signature(text: str | None) -> np.ndarray | None:
    """อ่านกลับจาก DB — คืน None ถ้าว่าง หรือข้อมูลผิดรูป"""
    if not text:
        return None
    try:
        raw = base64.b64decode(text)
    except ValueError:
        return None
    if len(raw) != SIG_SIZE * SIG_SIZE:
        return None
    return np.frombuffer(raw, dtype=np.uint8).reshape(SIG_SIZE, SIG_SIZE)


def similarity(a: np.ndarray, b: np.ndarray) -> float | None:
    """ความเหมือนของภาพย่อ 2 ภาพ (normalized cross-correlation: 1 = เหมือน, 0 = ไม่เกี่ยวกัน)

    คืน None ถ้าภาพใดภาพหนึ่งเรียบเกินไปจนเทียบไม่ได้ (เช่น กลางคืนมืดสนิท)
    """
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    std_a, std_b = float(a.std()), float(b.std())
    if std_a < MIN_TEXTURE_STD or std_b < MIN_TEXTURE_STD:
        return None
    return float(((a - a.mean()) * (b - b.mean())).mean() / (std_a * std_b))


def is_strong_detection(score: float, slot_threshold: float) -> bool:
    """AI เห็นรถในช่องชัดพอจะจำภาพช่องไว้หรือไม่ (กันจำภาพช่องว่างจากกรอบรถคันข้างที่ล้นเข้ามานิดหน่อย)"""
    return score >= max(slot_threshold, STRONG_SCORE)


def should_hold(
    raw_state: str,
    stored: np.ndarray | None,
    current: np.ndarray | None,
    held_since: datetime | None,
    now: datetime,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> bool:
    """AI บอกว่าว่าง แต่ภาพช่องยังเหมือนตอนที่เห็นรถ → ถือว่ารถคันเดิมยังจอดอยู่"""
    if raw_state != "free" or stored is None or current is None:
        return False
    if held_since is not None and now - held_since > MAX_HOLD:
        return False
    sim = similarity(stored, current)
    return sim is not None and sim >= min_similarity
